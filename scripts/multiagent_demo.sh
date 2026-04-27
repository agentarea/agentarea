#!/usr/bin/env bash
# Multi-agent demo against the running local stack.
#
# Drives a real "coordinator + 3 specialists" flow through the public API:
#   - file-writer:  saves a text file via agentarea/files
#   - pdf-fetcher:  downloads a PDF via agentarea/web (binary -> artifact)
#   - md-summarizer: fetches a Wikipedia page, summarizes to markdown
#
# The coordinator delegates to all three via the auto-generated
# delegate_to_<name> A2A tools, then completes with a roll-up.
#
# Requires the dev stack to be up:
#     make up-dev
#
# Output is human-readable; the script fails loudly on the first non-2xx.

set -euo pipefail

KRATOS_ADMIN="${KRATOS_ADMIN_URL:-http://localhost:4434}"
KRATOS_PUBLIC="${KRATOS_PUBLIC_URL:-http://localhost:4433}"
API="${API_URL:-http://localhost:8000}"
LLM_PROVIDER_KEY="${OPENAI_COMPAT_PROVIDER_KEY:-e2e-openai-compat}"
LLM_ENDPOINT="${OPENAI_COMPAT_ENDPOINT:-http://host.docker.internal:20128/v1}"
LLM_MODEL="${OPENAI_COMPAT_MODEL:-kr/claude-sonnet-4.5}"
LLM_API_KEY="${OPENAI_COMPAT_API_KEY:-}"
PDF_URL="${PDF_URL:-https://www.africau.edu/images/default/sample.pdf}"
WIKI_URL="${WIKI_URL:-https://en.wikipedia.org/wiki/Markdown}"

PG="docker exec agentarea-db-1 /usr/bin/psql -U postgres -d agentarea -tA -c"

step() { printf "\n\033[1;36m== %s ==\033[0m\n" "$*"; }
note() { printf "  %s\n" "$*"; }
fail() { printf "\033[1;31mFAIL: %s\033[0m\n" "$*" >&2; exit 1; }

require() {
  local code="$1" expected="$2" body="$3" what="$4"
  if [[ "$code" != "$expected" ]]; then
    fail "$what -> HTTP $code (expected $expected): $body"
  fi
}

step "Mint Kratos identity"
EMAIL="alice-mad-$(date +%s)@demo.local"
PASS="Str0ng-Demo-PW-xyz!"
IDENT_JSON=$(curl -sS -X POST "$KRATOS_ADMIN/admin/identities" \
  -H 'Content-Type: application/json' \
  -d "{
    \"schema_id\":\"default\",
    \"traits\":{\"email\":\"$EMAIL\"},
    \"credentials\":{\"password\":{\"config\":{\"password\":\"$PASS\"}}},
    \"verifiable_addresses\":[{\"value\":\"$EMAIL\",\"verified\":true,\"via\":\"email\",\"status\":\"completed\"}]
  }")
IDENT_ID=$(echo "$IDENT_JSON" | jq -r .id)
[[ "$IDENT_ID" != "null" && -n "$IDENT_ID" ]] || fail "no identity id: $IDENT_JSON"
note "$EMAIL ($IDENT_ID)"

step "Login + tokenize JWT"
FLOW=$(curl -sS "$KRATOS_PUBLIC/self-service/login/api" | jq -r .id)
SESSION=$(curl -sS -X POST "$KRATOS_PUBLIC/self-service/login?flow=$FLOW" \
  -H 'Content-Type: application/json' \
  -d "{\"method\":\"password\",\"identifier\":\"$EMAIL\",\"password\":\"$PASS\"}" | jq -r .session_token)
JWT=$(curl -sS "$KRATOS_PUBLIC/sessions/whoami?tokenize_as=agentarea_jwt" \
  -H "X-Session-Token: $SESSION" | jq -r .tokenized)
[[ -n "$JWT" && "$JWT" != "null" ]] || fail "no JWT"
note "JWT acquired (len=${#JWT})"

H=( -H "Authorization: Bearer $JWT" -H 'Content-Type: application/json' )

step "Resolve provider_spec + model_spec"
PROV_ID=$($PG "SELECT id FROM provider_specs WHERE provider_key='$LLM_PROVIDER_KEY';" | tr -d '[:space:]')
[[ -n "$PROV_ID" ]] || fail "provider_spec '$LLM_PROVIDER_KEY' missing — run e2e tests first to seed"
$PG "INSERT INTO model_specs(id,provider_spec_id,model_name,display_name,context_window,is_active,workspace_id,created_by) VALUES (gen_random_uuid(),'$PROV_ID','$LLM_MODEL','$LLM_MODEL',200000,true,'system','system') ON CONFLICT (provider_spec_id, model_name) DO NOTHING;" >/dev/null
MSPEC_ID=$($PG "SELECT id FROM model_specs WHERE provider_spec_id='$PROV_ID' AND model_name='$LLM_MODEL';" | tr -d '[:space:]')
note "provider_spec=$PROV_ID model_spec=$MSPEC_ID"

step "Create provider_config + model_instance"
PC=$(curl -sS -X POST "$API/v1/provider-configs/" "${H[@]}" \
  -d "{\"provider_spec_id\":\"$PROV_ID\",\"name\":\"demo-$(date +%s)\",\"api_key\":\"$LLM_API_KEY\",\"endpoint_url\":\"$LLM_ENDPOINT\"}")
PC_ID=$(echo "$PC" | jq -r .id)
[[ "$PC_ID" != "null" ]] || fail "provider_config: $PC"
MI=$(curl -sS -X POST "$API/v1/model-instances/" "${H[@]}" \
  -d "{\"provider_config_id\":\"$PC_ID\",\"model_spec_id\":\"$MSPEC_ID\",\"name\":\"demo-mi-$(date +%s)\"}")
MODEL_ID=$(echo "$MI" | jq -r .id)
[[ "$MODEL_ID" != "null" ]] || fail "model_instance: $MI"
note "model_id=$MODEL_ID"

create_agent() {
  local NAME="$1" INSTR="$2" TOOLS="$3"
  local BODY="{\"name\":\"$NAME\",\"description\":\"demo\",\"instruction\":$(jq -Rs . <<<"$INSTR"),\"model_id\":\"$MODEL_ID\",\"agent_type\":\"chat\",\"tools\":$TOOLS}"
  curl -sS -X POST "$API/v1/agents/" "${H[@]}" -d "$BODY"
}

step "Create specialist: file-writer"
FW=$(create_agent \
  "file-writer-$(date +%s)" \
  "You write text files on demand. The user will tell you a filename and contents. Call save_file once with those exact arguments, then call completion with one short sentence describing what you wrote." \
  '[{"type":"code","name":"agentarea/files"}]')
FW_ID=$(echo "$FW" | jq -r .id)
FW_NAME=$(echo "$FW" | jq -r .name)
[[ "$FW_ID" != "null" ]] || fail "file-writer create: $FW"
note "$FW_NAME ($FW_ID)"

step "Create specialist: pdf-fetcher"
PF=$(create_agent \
  "pdf-fetcher-$(date +%s)" \
  "You download PDFs from URLs. The user gives you a URL. Call fetch_webpage with that URL once. Then call completion with the artifact_path returned by the tool." \
  '[{"type":"code","name":"agentarea/web"},{"type":"code","name":"agentarea/files"}]')
PF_ID=$(echo "$PF" | jq -r .id)
PF_NAME=$(echo "$PF" | jq -r .name)
[[ "$PF_ID" != "null" ]] || fail "pdf-fetcher create: $PF"
note "$PF_NAME ($PF_ID)"

step "Create specialist: md-summarizer"
MS=$(create_agent \
  "md-summarizer-$(date +%s)" \
  "You produce markdown summaries of web pages. The user gives you a URL. (1) Call fetch_webpage on it. (2) Write a 5-bullet markdown summary into a file named summary.md using save_file. (3) Call completion with the filename." \
  '[{"type":"code","name":"agentarea/web"},{"type":"code","name":"agentarea/files"}]')
MS_ID=$(echo "$MS" | jq -r .id)
MS_NAME=$(echo "$MS" | jq -r .name)
[[ "$MS_ID" != "null" ]] || fail "md-summarizer create: $MS"
note "$MS_NAME ($MS_ID)"

step "Create coordinator with 3 delegate_to_* tools"
COORD_TOOLS=$(jq -nc \
  --arg fw "$FW_NAME" --arg pf "$PF_NAME" --arg ms "$MS_NAME" \
  '[{"type":"agent","name":$fw},{"type":"agent","name":$pf},{"type":"agent","name":$ms}]')
COORD=$(create_agent \
  "coordinator-$(date +%s)" \
  "You coordinate three specialist agents. For the user's request, call all three delegate_to_* tools (one per specialist) with appropriate, specific messages. After all three return, call completion with a short paragraph summarizing each specialist's result." \
  "$COORD_TOOLS")
COORD_ID=$(echo "$COORD" | jq -r .id)
COORD_NAME=$(echo "$COORD" | jq -r .name)
[[ "$COORD_ID" != "null" ]] || fail "coordinator create: $COORD"
note "$COORD_NAME ($COORD_ID)"

step "Submit task to coordinator"
PROMPT="Please run all three subagents:
(1) Tell $FW_NAME to save the contents 'hello from coordinator' into a file named greeting.txt.
(2) Tell $PF_NAME to download the PDF at $PDF_URL.
(3) Tell $MS_NAME to fetch $WIKI_URL and produce a markdown summary into summary.md.
Then summarize what each one did."
TASK=$(curl -sS -X POST "$API/v1/agents/$COORD_ID/tasks/sync" "${H[@]}" \
  -d "{\"description\":$(jq -Rs . <<<"$PROMPT")}" --max-time 30)
TASK_ID=$(echo "$TASK" | jq -r .id)
[[ "$TASK_ID" != "null" ]] || fail "task submit: $TASK"
note "task=$TASK_ID"

step "Poll events until WorkflowCompleted (up to 5 min)"
DEADLINE=$(( $(date +%s) + 300 ))
LAST_TYPES=""
while [[ $(date +%s) -lt $DEADLINE ]]; do
  EV=$(curl -sS "$API/v1/agents/$COORD_ID/tasks/$TASK_ID/events" "${H[@]}")
  TYPES=$(echo "$EV" | jq -r '.events[].event_type' | sort | uniq -c | awk '{printf "%s:%s ", $2,$1}')
  if [[ "$TYPES" != "$LAST_TYPES" ]]; then
    note "[$(date +%H:%M:%S)] $TYPES"
    LAST_TYPES="$TYPES"
  fi
  if echo "$EV" | jq -e '.events[] | select(.event_type=="WorkflowFailed" or .event_type=="LLMCallFailed")' >/dev/null 2>&1; then
    note "FAILED EVENT:"
    echo "$EV" | jq '.events[] | select(.event_type=="WorkflowFailed" or .event_type=="LLMCallFailed")'
    fail "workflow reported failure"
  fi
  if echo "$EV" | jq -e '.events[] | select(.event_type=="WorkflowCompleted")' >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

step "Final coordinator response"
FINAL=$(curl -sS "$API/v1/agents/$COORD_ID/tasks/$TASK_ID" "${H[@]}")
echo "$FINAL" | jq '{status, result}'

step "Tool calls observed (coordinator)"
curl -sS "$API/v1/agents/$COORD_ID/tasks/$TASK_ID/events" "${H[@]}" \
  | jq -r '.events[] | select(.event_type=="ToolCallStarted") | .metadata.tool_name' \
  | sort | uniq -c

step "List subtasks created via delegation"
docker exec agentarea-db-1 /usr/bin/psql -U postgres -d agentarea -tA -c \
  "SELECT t.id, t.agent_id, t.status, t.description FROM tasks t WHERE t.created_at > now() - interval '10 min' AND (t.metadata->>'source')='agent_delegation' ORDER BY t.created_at;" || true

step "List artifacts produced (RustFS objects under each task)"
docker exec agentarea-db-1 /usr/bin/psql -U postgres -d agentarea -tA -c \
  "SELECT t.id, t.description FROM tasks t WHERE t.created_at > now() - interval '10 min' ORDER BY t.created_at;"

# Best-effort: cancel coordinator to release the await_input window.
curl -sS -X DELETE "$API/v1/agents/$COORD_ID/tasks/$TASK_ID" "${H[@]}" >/dev/null || true

step "Cleanup Kratos identity"
curl -sS -X DELETE "$KRATOS_ADMIN/admin/identities/$IDENT_ID" >/dev/null || true
note "done"
