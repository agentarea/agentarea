#!/usr/bin/env bash
# test-sandbox-docx.sh — proves the bash sandbox can pull an external Python
# library, install it, run a real generation script, and produce a valid
# .docx file. Same pod-stickiness model as test-sandbox-k3d.sh, but the
# scenario exercises pip/git, persistent venv, binary file production, and
# round-tripping the artefact back to the host.
#
# What this proves end-to-end:
#   1. `git clone` works inside the sandbox pod.
#   2. `pip install` (PyPI access + DNS) installs python-docx into the
#      persistent /workspace/wf-<id>/venv so it survives between calls.
#   3. The agent-style script that generates a commercial offer .docx
#      actually produces a real Office Open XML file.
#   4. The file can be retrieved (kubectl cp) and verified — `file` reports
#      Microsoft Word 2007+ and the embedded XML contains the expected
#      content. This is the strongest possible "the sandbox works" signal.
#
# Requirements: scripts/test-sandbox-k3d.sh has been adjusted to leave the
# cluster running (or this script will create it). Reuses the same image
# (rebuilt to include py3-pip).
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT=$(pwd)

CLUSTER=${CLUSTER:-sandbox-test}
IMAGE=${SANDBOX_IMAGE:-agentarea/sandbox-executor:e2e}
NAMESPACE=mcp-system
WORKFLOW_ID="wf-docx-$(date +%s)"
PORT=${PORT:-18181}
KCTX="k3d-${CLUSTER}"
kctl() { kubectl --context "${KCTX}" "$@"; }

step() { printf '\n\033[1;34m▸ %s\033[0m\n' "$1"; }
ok()   { printf '\033[32m✓ %s\033[0m\n' "$1"; }
fail() { printf '\033[31m✗ %s\033[0m\n' "$1"; exit 1; }

PORT_FORWARD_PID=""
ARTIFACT_DIR=$(mktemp -d)
cleanup() {
  if [[ -n "${PORT_FORWARD_PID}" ]] && kill -0 "${PORT_FORWARD_PID}" 2>/dev/null; then
    kill "${PORT_FORWARD_PID}" 2>/dev/null || true
  fi
  if [[ "${KEEP_CLUSTER:-1}" != "1" ]]; then
    k3d cluster delete "${CLUSTER}" >/dev/null 2>&1 || true
  fi
  if [[ "${KEEP_ARTIFACTS:-0}" != "1" ]]; then
    rm -rf "${ARTIFACT_DIR}" || true
  else
    printf '\033[33m  artifact dir kept: %s\033[0m\n' "${ARTIFACT_DIR}"
  fi
}
trap cleanup EXIT

step "Rebuilding sandbox-executor image (py3-pip + git for docx generation)"
docker build -q -t "${IMAGE}" -f agentarea-mcp-manager/Dockerfile.sandbox agentarea-mcp-manager/ >/dev/null \
  || fail "image build failed"
ok "image built"

step "Ensuring k3d cluster '${CLUSTER}' exists"
if ! k3d cluster list 2>/dev/null | grep -q "^${CLUSTER}\b"; then
  k3d cluster create "${CLUSTER}" --agents 0 --wait >/dev/null \
    || fail "k3d cluster create failed"
fi
k3d image import "${IMAGE}" -c "${CLUSTER}" >/dev/null 2>&1 \
  || fail "k3d image import failed"
ok "cluster + image ready"

POD=sandbox-docx-test
step "Recreating pod ${POD} with the new image"
kctl delete pod "${POD}" -n "${NAMESPACE}" --ignore-not-found --wait=true >/dev/null 2>&1 || true
cat <<YAML | kctl apply -f - >/dev/null
apiVersion: v1
kind: Namespace
metadata: { name: ${NAMESPACE} }
---
apiVersion: v1
kind: Pod
metadata:
  name: ${POD}
  namespace: ${NAMESPACE}
  labels:
    app.kubernetes.io/component: warm-pool
    mcp.agentarea.io/status: waiting
spec:
  restartPolicy: Never
  dnsPolicy: Default
  containers:
  - name: activation-service
    image: ${IMAGE}
    imagePullPolicy: IfNotPresent
    ports: [{ containerPort: 8080, name: http }]
    env:
    - { name: WORKSPACE_ROOT, value: /workspace }
    volumeMounts: [{ name: workspace, mountPath: /workspace }]
    readinessProbe: { httpGet: { path: /health, port: 8080 }, initialDelaySeconds: 1, periodSeconds: 1 }
  volumes: [{ name: workspace, emptyDir: {} }]
---
apiVersion: v1
kind: Service
metadata:
  name: ${POD}
  namespace: ${NAMESPACE}
spec:
  selector: { mcp.agentarea.io/status: waiting }
  ports: [{ port: 8080, targetPort: 8080 }]
YAML
kctl wait --for=condition=ready pod/${POD} -n "${NAMESPACE}" --timeout=60s >/dev/null \
  || fail "pod did not become ready"
ok "pod ready"

step "Port-forwarding to localhost:${PORT}"
kctl -n "${NAMESPACE}" port-forward "pod/${POD}" "${PORT}:8080" >/dev/null 2>&1 &
PORT_FORWARD_PID=$!
for _ in $(seq 1 30); do
  curl -sf "http://localhost:${PORT}/health" >/dev/null 2>&1 && break
  sleep 0.5
done
curl -sf "http://localhost:${PORT}/health" >/dev/null || fail "port-forward never came up"
ok "port-forward active"

execute() {
  local content="$1" tmo="${2:-120}"
  curl -sf -X POST "http://localhost:${PORT}/execute" \
    -H 'Content-Type: application/json' \
    -d "$(jq -n --arg c "$content" --arg w "$WORKFLOW_ID" --argjson t "$tmo" \
            '{script_name:"cmd.sh", script_content:$c, workflow_id:$w, timeout_seconds:$t}')"
}
require_zero() {
  local label="$1" resp="$2"
  local code stderr
  code=$(echo "$resp" | jq -r .exit_code)
  stderr=$(echo "$resp" | jq -r .stderr)
  [[ "$code" == "0" ]] || fail "${label}: exit=${code}, stderr=${stderr}"
}

step "Step 1 — clone python-docx repo into the sandbox (proves git+DNS)"
RESP=$(execute 'git clone --depth=1 https://github.com/python-openxml/python-docx.git repo 2>&1 | tail -3 && test -f repo/README.md && find repo -maxdepth 3 -name "__init__.py" | head -1')
require_zero "git clone" "$RESP"
ok "repo cloned, init at: $(echo "$RESP" | jq -r .stdout | tail -1)"

step "Step 2 — create persistent venv + pip install python-docx (proves pip+PyPI)"
RESP=$(execute 'python3 -m venv venv && . venv/bin/activate && pip install --quiet python-docx && python3 -c "import docx; print(\"docx version:\", docx.__version__ if hasattr(docx,\"__version__\") else \"installed\")"' 180)
require_zero "pip install" "$RESP"
ok "$(echo "$RESP" | jq -r .stdout)"

step "Step 3 — write a commercial-offer generator script and run it"
GEN_SCRIPT='
cat > make_offer.py <<'\''PY'\''
from docx import Document
from docx.shared import Pt, Inches
from datetime import date

doc = Document()
title = doc.add_heading("Commercial Offer", level=0)
doc.add_paragraph(f"Date: {date.today().isoformat()}")
doc.add_paragraph("To: ACME Corp")
doc.add_paragraph("From: AgentArea Demo")

doc.add_heading("Scope", level=1)
doc.add_paragraph(
    "Implementation of a per-workflow bash sandbox with pod-level state "
    "persistence across multiple tool calls within a single Temporal task."
)

doc.add_heading("Pricing", level=1)
table = doc.add_table(rows=1, cols=3)
table.style = "Light Grid Accent 1"
hdr = table.rows[0].cells
hdr[0].text = "Item"
hdr[1].text = "Qty"
hdr[2].text = "Price"
for item, qty, price in [
    ("Sandbox runtime", "1", "$0"),
    ("Workflow-scoped workspace", "1", "$0"),
    ("Cleanup on completion", "1", "$0"),
]:
    row = table.add_row().cells
    row[0].text, row[1].text, row[2].text = item, qty, price

doc.add_paragraph("\nGenerated entirely inside the sandbox pod.")
doc.save("offer.docx")
print("WROTE offer.docx", end="")
PY
. venv/bin/activate && python3 make_offer.py && ls -la offer.docx && echo DONE'
RESP=$(execute "$GEN_SCRIPT")
require_zero "generate offer.docx" "$RESP"
STDOUT=$(echo "$RESP" | jq -r .stdout)
[[ "$STDOUT" == *"DONE"* ]] || fail "generator did not finish: $STDOUT"
ok "offer.docx generated inside the pod"

step "Step 4 — kubectl cp the .docx back to the host and verify"
kctl -n "${NAMESPACE}" cp "${POD}:/workspace/wf-${WORKFLOW_ID}/offer.docx" "${ARTIFACT_DIR}/offer.docx" >/dev/null \
  || fail "kubectl cp failed"
[[ -s "${ARTIFACT_DIR}/offer.docx" ]] || fail "copied file is empty"

# `file` is a portable way to verify Office Open XML signatures.
FILE_TYPE=$(file "${ARTIFACT_DIR}/offer.docx" | tail -1)
case "$FILE_TYPE" in
  *Microsoft\ Word*|*"Microsoft OOXML"*|*"Word 2007+"*|*"Zip archive"*) ;;
  *) fail "file(1) reports unexpected type: ${FILE_TYPE}" ;;
esac
ok "host file says: ${FILE_TYPE}"

# Inspect the embedded XML for the content we asked the script to write.
unzip -p "${ARTIFACT_DIR}/offer.docx" word/document.xml > "${ARTIFACT_DIR}/document.xml" 2>/dev/null \
  || fail "could not extract document.xml from offer.docx"
for needle in "Commercial Offer" "ACME Corp" "Sandbox runtime"; do
  grep -q "$needle" "${ARTIFACT_DIR}/document.xml" \
    || fail "document.xml missing expected content: ${needle}"
done
ok "document.xml contains: Commercial Offer / ACME Corp / Sandbox runtime"

step "Step 5 — second pod call uses the persisted venv (no reinstall)"
RESP=$(execute '. venv/bin/activate && python3 -c "import docx; print(\"OK reused venv from previous call\")"')
require_zero "reuse venv" "$RESP"
ok "$(echo "$RESP" | jq -r .stdout)"

step "Cleanup — DELETE workflow workspace"
curl -sf -X POST "http://localhost:${PORT}/workspace/cleanup" \
  -H 'Content-Type: application/json' \
  -d "$(jq -n --arg w "$WORKFLOW_ID" '{workflow_id:$w}')" >/dev/null \
  || fail "cleanup failed"
RESP=$(execute 'ls 2>&1; test ! -d venv && echo VENV_GONE')
STDOUT=$(echo "$RESP" | jq -r .stdout)
[[ "$STDOUT" == *"VENV_GONE"* ]] || fail "venv survived cleanup: $STDOUT"
ok "post-cleanup workspace is fresh (venv + repo gone)"

printf '\n\033[1;32m✓ End-to-end docx generation in the K8s sandbox proven.\033[0m\n'
printf '   Artefact saved: %s/offer.docx\n' "${ARTIFACT_DIR}"
KEEP_ARTIFACTS=1
