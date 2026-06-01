#!/usr/bin/env bash
# test-sandbox-k3d.sh — proves the per-workflow bash sandbox works inside a
# real Kubernetes pod (k3d), not just a docker container. The runtime
# semantics that matter under K8s are:
#
#   1. /workspace mounted as emptyDir lives with the pod (not the host)
#   2. Files written into /workspace/wf-<id>/ persist across HTTP calls to
#      the same pod — exactly what mcp-manager relies on for warm-pool
#      stickiness via FindOrAssignPodForWorkflow.
#   3. Cleanup via POST /workspace/cleanup actually clears the dir inside
#      the pod, not just on the host.
#
# This script does NOT bring up the full platform (no Postgres, Temporal,
# API, worker). The agent → mcp-manager → pod path is exercised by the
# Python toolset tests + Go unit tests; what's left to verify against a
# real cluster is the pod-side runtime, which this script does.
#
# Requirements: k3d, kubectl, docker. Image agentarea/sandbox-executor:e2e
# (build with scripts/test-sandbox-e2e.sh first, or set REBUILD=1 here).
#
# Usage:
#   scripts/test-sandbox-k3d.sh           # use existing image
#   REBUILD=1 scripts/test-sandbox-k3d.sh # build image fresh first
#   KEEP_CLUSTER=1 scripts/test-sandbox-k3d.sh  # don't tear down on exit
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT=$(pwd)

CLUSTER=${CLUSTER:-sandbox-test}
IMAGE=${SANDBOX_IMAGE:-agentarea/sandbox-executor:e2e}
NAMESPACE=mcp-system
WORKFLOW_ID="wf-k3d-$(date +%s)"
PORT=${PORT:-18180}
# Pin kubectl to the k3d cluster's context so we never accidentally talk to
# whatever the user's current-context happens to be (a remote prod cluster,
# a DigitalOcean cluster, etc.). All kubectl calls below use --context.
KCTX="k3d-${CLUSTER}"
kctl() { kubectl --context "${KCTX}" "$@"; }

step() { printf '\n\033[1;34m▸ %s\033[0m\n' "$1"; }
ok()   { printf '\033[32m✓ %s\033[0m\n' "$1"; }
fail() { printf '\033[31m✗ %s\033[0m\n' "$1"; exit 1; }

PORT_FORWARD_PID=""
cleanup() {
  if [[ -n "${PORT_FORWARD_PID}" ]] && kill -0 "${PORT_FORWARD_PID}" 2>/dev/null; then
    kill "${PORT_FORWARD_PID}" 2>/dev/null || true
  fi
  if [[ "${KEEP_CLUSTER:-0}" != "1" ]]; then
    k3d cluster delete "${CLUSTER}" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

if [[ "${REBUILD:-0}" == "1" ]] || ! docker image inspect "${IMAGE}" >/dev/null 2>&1; then
  step "Building sandbox-executor image (${IMAGE})"
  docker build -q -t "${IMAGE}" -f agentarea-mcp-manager/Dockerfile.sandbox agentarea-mcp-manager/ >/dev/null \
    || fail "image build failed"
  ok "image built"
fi

step "Creating k3d cluster '${CLUSTER}'"
if k3d cluster list 2>/dev/null | grep -q "^${CLUSTER}\b"; then
  ok "cluster already exists, reusing"
else
  k3d cluster create "${CLUSTER}" --agents 0 --wait >/dev/null \
    || fail "k3d cluster create failed"
  ok "cluster created"
fi

step "Importing image into cluster"
k3d image import "${IMAGE}" -c "${CLUSTER}" >/dev/null 2>&1 \
  || fail "k3d image import failed"
ok "image imported"

step "Applying namespace + sandbox pod + service"
cat <<YAML | kctl apply -f - >/dev/null
apiVersion: v1
kind: Namespace
metadata:
  name: ${NAMESPACE}
---
apiVersion: v1
kind: Pod
metadata:
  name: sandbox-warmpool-test
  namespace: ${NAMESPACE}
  labels:
    app.kubernetes.io/component: warm-pool
    mcp.agentarea.io/status: waiting
spec:
  restartPolicy: Never
  # dnsPolicy: ClusterFirst (default) routes through CoreDNS, which on
  # k3d-on-macOS sometimes can't reach external internet. Default uses
  # the node's resolv.conf — for a k3d node (a docker container) that
  # falls through to docker's DNS which can resolve the public internet.
  dnsPolicy: Default
  containers:
  - name: activation-service
    image: ${IMAGE}
    imagePullPolicy: IfNotPresent
    ports:
    - containerPort: 8080
      name: http
    env:
    - name: WORKSPACE_ROOT
      value: /workspace
    - name: IDLE_TIMEOUT_SECONDS
      value: "3600"
    volumeMounts:
    - name: workspace
      mountPath: /workspace
    readinessProbe:
      httpGet: { path: /health, port: 8080 }
      initialDelaySeconds: 1
      periodSeconds: 1
  volumes:
  - name: workspace
    emptyDir: {}
---
apiVersion: v1
kind: Service
metadata:
  name: sandbox-warmpool-test
  namespace: ${NAMESPACE}
spec:
  selector:
    app.kubernetes.io/component: warm-pool
    mcp.agentarea.io/status: waiting
  ports:
  - port: 8080
    targetPort: 8080
YAML
ok "manifests applied"

step "Waiting for pod ready"
kctl -n "${NAMESPACE}" wait --for=condition=ready pod/sandbox-warmpool-test --timeout=60s >/dev/null \
  || fail "pod did not become ready"
ok "pod ready"

step "Port-forwarding service to localhost:${PORT}"
kctl -n "${NAMESPACE}" port-forward svc/sandbox-warmpool-test "${PORT}:8080" >/dev/null 2>&1 &
PORT_FORWARD_PID=$!
for _ in $(seq 1 30); do
  if curl -sf "http://localhost:${PORT}/health" >/dev/null 2>&1; then
    ok "port-forward active"
    break
  fi
  sleep 0.5
done
curl -sf "http://localhost:${PORT}/health" >/dev/null || fail "port-forward never came up"

execute() {
  local content="$1"
  curl -sf -X POST "http://localhost:${PORT}/execute" \
    -H 'Content-Type: application/json' \
    -d "$(jq -n --arg c "$content" --arg w "$WORKFLOW_ID" \
            '{script_name:"cmd.sh", script_content:$c, workflow_id:$w, timeout_seconds:60}')"
}

assert_in() {
  local needle="$1" haystack="$2" label="$3"
  if [[ "$haystack" != *"$needle"* ]]; then
    fail "${label}: expected '${needle}' in output, got: ${haystack}"
  fi
}

step "Call 1 — curl into pod's emptyDir workspace"
RESP=$(execute 'curl -sS https://httpbin.org/json -o data.json && wc -c < data.json')
EXIT=$(echo "$RESP" | jq -r .exit_code)
[[ "$EXIT" == "0" ]] || fail "call 1 exit=${EXIT}, stderr=$(echo "$RESP" | jq -r .stderr)"
ok "curl wrote data.json"

step "Call 2 — read file (proves pod-level persistence)"
RESP=$(execute 'cat data.json | head -c 80')
STDOUT=$(echo "$RESP" | jq -r .stdout)
assert_in "slideshow" "$STDOUT" "call 2"
ok "pod kept call 1's file"

step "Call 3 — npm install lodash inside the pod"
RESP=$(execute 'npm init -y >/dev/null 2>&1 && npm install --silent --no-fund --no-audit lodash 2>&1 && echo OK')
EXIT=$(echo "$RESP" | jq -r .exit_code)
[[ "$EXIT" == "0" ]] || fail "npm install failed: $(echo "$RESP" | jq -r .stderr)"
ok "lodash installed inside pod"

step "Call 4 — node uses persisted lodash"
RESP=$(execute 'node -e "console.log(JSON.stringify(require(\"lodash\").chunk([1,2,3,4],2)))"')
STDOUT=$(echo "$RESP" | jq -r .stdout)
assert_in "[[1,2],[3,4]]" "$STDOUT" "call 4"
ok "node ran with persisted node_modules: ${STDOUT}"

step "Cleanup workspace via /workspace/cleanup"
curl -sf -X POST "http://localhost:${PORT}/workspace/cleanup" \
  -H 'Content-Type: application/json' \
  -d "$(jq -n --arg w "$WORKFLOW_ID" '{workflow_id:$w}')" >/dev/null \
  || fail "cleanup failed"
ok "cleanup ack"

step "Call 5 — workspace must be fresh post-cleanup"
RESP=$(execute 'ls 2>&1; cat data.json 2>&1 || true')
STDOUT=$(echo "$RESP" | jq -r .stdout)
[[ "$STDOUT" != *"slideshow"* ]] || fail "data.json survived cleanup"
[[ "$STDOUT" != *"node_modules"* ]] || fail "node_modules survived cleanup"
ok "workspace fresh after cleanup"

step "Verify the K8s pod itself is still healthy + waiting"
PHASE=$(kctl -n "${NAMESPACE}" get pod sandbox-warmpool-test -o jsonpath='{.status.phase}')
[[ "$PHASE" == "Running" ]] || fail "pod phase is ${PHASE}, expected Running"
ok "warm-pool pod still Running (ready for next workflow)"

printf '\n\033[1;32m✓ Sandbox proven inside a real K8s pod.\033[0m\n'
