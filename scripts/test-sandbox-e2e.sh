#!/usr/bin/env bash
# test-sandbox-e2e.sh — end-to-end proof that the per-workflow bash sandbox
# actually runs commands, persists state across calls, and tears down on
# cleanup. Runs the real sandbox-executor container (same image used in
# prod / docker-compose) so this is a faithful test of the runtime, not a
# stub.
#
# What this proves:
#   1. /sandbox/execute with workflow_id routes into /workspace/wf-<id>/
#   2. Files written by call N are readable by call N+1 in the same workflow
#   3. `npm install` from one call persists for `node -e require(...)` in the next
#   4. /workspace/cleanup actually wipes the dir
#   5. After cleanup, a fresh execute on the same id sees an empty workspace
#
# What this does NOT cover (separate paths):
#   - mcp-manager routing (POST /sandbox/execute on mcp-manager) — covered by
#     the Go unit tests + the docker-compose stack
#   - K8s warm-pool pod stickiness — covered by scripts/test-sandbox-k3d.sh
#   - Agent → tool → mcp-manager wiring — covered by the Python toolset tests
#
# Usage:
#   scripts/test-sandbox-e2e.sh           # builds image, runs scenario
#   SKIP_BUILD=1 scripts/test-sandbox-e2e.sh  # reuses existing image
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT=$(pwd)

IMAGE=${SANDBOX_IMAGE:-agentarea/sandbox-executor:e2e}
PORT=${PORT:-18080}
CONTAINER=sandbox-e2e-test-$$
WORKFLOW_ID="wf-$(date +%s)-$RANDOM"

step() { printf '\n\033[1;34m▸ %s\033[0m\n' "$1"; }
ok()   { printf '\033[32m✓ %s\033[0m\n' "$1"; }
fail() { printf '\033[31m✗ %s\033[0m\n' "$1"; exit 1; }

cleanup() {
  if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER}$"; then
    docker rm -f "${CONTAINER}" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

if [[ "${SKIP_BUILD:-0}" != "1" ]]; then
  step "Building sandbox-executor image (${IMAGE})"
  docker build -q -t "${IMAGE}" -f agentarea-mcp-manager/Dockerfile.sandbox agentarea-mcp-manager/ >/dev/null \
    || fail "image build failed"
  ok "image built"
else
  step "Reusing existing image (${IMAGE})"
fi

step "Starting sandbox-executor container on :${PORT}"
docker run -d --rm \
  --name "${CONTAINER}" \
  -p "${PORT}:8080" \
  -e WORKSPACE_ROOT=/workspace \
  "${IMAGE}" >/dev/null
ok "container started"

step "Waiting for /health"
for _ in $(seq 1 30); do
  if curl -sf "http://localhost:${PORT}/health" >/dev/null 2>&1; then
    ok "service is up"
    break
  fi
  sleep 0.5
done
curl -sf "http://localhost:${PORT}/health" >/dev/null || fail "service never came up"

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

step "Call 1 — fetch a file via curl into the workspace"
RESP=$(execute 'curl -sS https://httpbin.org/json -o data.json && wc -c < data.json')
EXIT=$(echo "$RESP" | jq -r .exit_code)
STDOUT=$(echo "$RESP" | jq -r .stdout)
[[ "$EXIT" == "0" ]] || fail "call 1 exit=${EXIT}, stderr=$(echo "$RESP" | jq -r .stderr)"
ok "curl wrote data.json (${STDOUT// /} bytes)"

step "Call 2 — read the file written by call 1 (proves persistence)"
RESP=$(execute 'cat data.json | head -c 80')
EXIT=$(echo "$RESP" | jq -r .exit_code)
STDOUT=$(echo "$RESP" | jq -r .stdout)
[[ "$EXIT" == "0" ]] || fail "call 2 exit=${EXIT}, stderr=$(echo "$RESP" | jq -r .stderr)"
assert_in "slideshow" "$STDOUT" "call 2"
ok "call 2 saw call 1's file: ${STDOUT:0:60}…"

step "Call 3 — npm init + install lodash into the workspace"
RESP=$(execute 'npm init -y >/dev/null 2>&1 && npm install --silent --no-fund --no-audit lodash 2>&1 && echo INSTALLED')
EXIT=$(echo "$RESP" | jq -r .exit_code)
STDOUT=$(echo "$RESP" | jq -r .stdout)
[[ "$EXIT" == "0" ]] || fail "call 3 exit=${EXIT}, stderr=$(echo "$RESP" | jq -r .stderr)"
assert_in "INSTALLED" "$STDOUT" "call 3"
ok "lodash installed"

step "Call 4 — use lodash from a node one-liner (proves node_modules survived)"
RESP=$(execute 'node -e "const _ = require(\"lodash\"); console.log(JSON.stringify(_.chunk([1,2,3,4],2)))"')
EXIT=$(echo "$RESP" | jq -r .exit_code)
STDOUT=$(echo "$RESP" | jq -r .stdout)
[[ "$EXIT" == "0" ]] || fail "call 4 exit=${EXIT}, stderr=$(echo "$RESP" | jq -r .stderr)"
assert_in "[[1,2],[3,4]]" "$STDOUT" "call 4"
ok "node used persisted lodash: ${STDOUT}"

step "Cleanup — POST /workspace/cleanup"
curl -sf -X POST "http://localhost:${PORT}/workspace/cleanup" \
  -H 'Content-Type: application/json' \
  -d "$(jq -n --arg w "$WORKFLOW_ID" '{workflow_id:$w}')" >/dev/null \
  || fail "cleanup endpoint returned non-2xx"
ok "cleanup acknowledged"

step "Call 5 — execute on same workflow_id should see empty workspace"
RESP=$(execute 'ls -1 . 2>&1; echo ---; cat data.json 2>&1 || true')
STDOUT=$(echo "$RESP" | jq -r .stdout)
if [[ "$STDOUT" == *"slideshow"* ]]; then
  fail "post-cleanup workspace still has data.json: ${STDOUT}"
fi
if [[ "$STDOUT" == *"node_modules"* ]]; then
  fail "post-cleanup workspace still has node_modules: ${STDOUT}"
fi
ok "post-cleanup workspace is fresh"

printf '\n\033[1;32m✓ All sandbox e2e checks passed.\033[0m\n'
