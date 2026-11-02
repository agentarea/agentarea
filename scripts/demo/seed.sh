#!/usr/bin/env bash
# Fill the local dev stack with a demo user and a demo workspace.
#
#   make demo-seed            # needs `make up-dev` and an imported catalog
#
# Signs in as DEMO_EMAIL (created on first run), then installs every catalog
# bundle into that user's workspace through the public API. Safe to rerun: an
# existing user is reused and an installed bundle is skipped. Local only: the
# password is a fixed, published value.

set -euo pipefail

KRATOS_ADMIN="${AGENTAREA_AUTH_KRATOS_ADMIN_URL:-http://localhost:4434}"
KRATOS_PUBLIC="${AGENTAREA_AUTH_KRATOS_URL:-http://localhost:4433}"
API="${AGENTAREA_API_URL:-http://localhost:8000}"
DEMO_EMAIL="${DEMO_EMAIL:-demo@agentarea.local}"
DEMO_PASSWORD="${DEMO_PASSWORD:-agentarea-demo-2026}"
# The demo agents' model, through OpenRouter. Without OPENROUTER_API_KEY the
# agents still install and show up, but a run fails at the first model call.
DEMO_MODEL="${DEMO_MODEL:-deepseek/deepseek-v3.2}"
OPENROUTER_API_KEY="${OPENROUTER_API_KEY:-}"
# Bundles with a Telegram channel need a real bot token; without one they are skipped.
DEMO_TELEGRAM_BOT_TOKEN="${DEMO_TELEGRAM_BOT_TOKEN:-}"

step() { printf "\n\033[1;36m== %s ==\033[0m\n" "$*"; }
note() { printf "  %s\n" "$*"; }
fail() { printf "\033[1;31mFAIL: %s\033[0m\n" "$*" >&2; exit 1; }

case "$API" in
  http://localhost*|http://127.0.0.1*) ;;
  *) fail "demo data goes to a local stack only, not $API" ;;
esac

step "Demo user"
existing=$(curl -sS "$KRATOS_ADMIN/admin/identities?credentials_identifier=$DEMO_EMAIL" | jq -r '.[0].id // empty')
if [[ -n "$existing" ]]; then
  note "$DEMO_EMAIL exists ($existing)"
else
  created=$(curl -sS -X POST "$KRATOS_ADMIN/admin/identities" -H 'Content-Type: application/json' -d "$(jq -nc \
    --arg e "$DEMO_EMAIL" --arg p "$DEMO_PASSWORD" '{
      schema_id: "default",
      traits: {email: $e},
      credentials: {password: {config: {password: $p}}},
      verifiable_addresses: [{value: $e, verified: true, via: "email", status: "completed"}]
    }')")
  id=$(jq -r '.id // empty' <<<"$created")
  [[ -n "$id" ]] || fail "creating $DEMO_EMAIL: $created"
  note "$DEMO_EMAIL created ($id)"
fi

step "Sign in"
flow=$(curl -sS "$KRATOS_PUBLIC/self-service/login/api" | jq -r .id)
session=$(curl -sS -X POST "$KRATOS_PUBLIC/self-service/login?flow=$flow" -H 'Content-Type: application/json' \
  -d "$(jq -nc --arg e "$DEMO_EMAIL" --arg p "$DEMO_PASSWORD" '{method: "password", identifier: $e, password: $p}')" \
  | jq -r '.session_token // empty')
[[ -n "$session" ]] || fail "sign-in failed for $DEMO_EMAIL (password changed? set DEMO_PASSWORD)"
jwt=$(curl -sS "$KRATOS_PUBLIC/sessions/whoami?tokenize_as=agentarea_jwt" -H "X-Session-Token: $session" | jq -r '.tokenized // empty')
[[ -n "$jwt" ]] || fail "no JWT for the session"
H=(-H "Authorization: Bearer $jwt" -H 'Content-Type: application/json')

# Listing workspaces provisions the user's personal one on first call.
workspace=$(curl -sS "$API/v1/workspaces" "${H[@]}" | jq -r '.[0].slug // empty')
[[ -n "$workspace" ]] || fail "no workspace for $DEMO_EMAIL"
WS="$API/v1/workspaces/$workspace"
note "workspace $workspace"

step "Model"
provider=$(curl -sS "$WS/provider-specs/" "${H[@]}" | jq -r '[.[] | select(.provider_key == "openrouter")][0].id // empty')
[[ -n "$provider" ]] || fail "no openrouter provider in the catalog: import llm-providers first"
spec=$(curl -sS "$WS/model-specs/by-provider/$provider" "${H[@]}" | jq -r --arg m "$DEMO_MODEL" '[.[] | select(.model_name == $m)][0].id // empty')
[[ -n "$spec" ]] || fail "$DEMO_MODEL is not an OpenRouter model of the catalog (set DEMO_MODEL to one that is)"
config=$(curl -sS "$WS/provider-configs/" "${H[@]}" | jq -r '[.[]? | select(.name == "Demo OpenRouter")][0].id // empty')
if [[ -z "$config" ]]; then
  config=$(curl -sS -X POST "$WS/provider-configs/" "${H[@]}" -d "$(jq -nc --arg p "$provider" --arg k "$OPENROUTER_API_KEY" \
    '{provider_spec_id: $p, name: "Demo OpenRouter"} + (if $k == "" then {} else {api_key: $k} end)')" | jq -r '.id // empty')
  [[ -n "$config" ]] || fail "creating the OpenRouter provider config"
fi
model=$(curl -sS "$WS/model-instances/" "${H[@]}" | jq -r --arg c "$config" '[.[]? | select(.provider_config_id == $c)][0].id // empty')
if [[ -z "$model" ]]; then
  model=$(curl -sS -X POST "$WS/model-instances/" "${H[@]}" -d "$(jq -nc --arg c "$config" --arg s "$spec" --arg n "$DEMO_MODEL" \
    '{provider_config_id: $c, model_spec_id: $s, name: $n}')" | jq -r '.id // empty')
  [[ -n "$model" ]] || fail "creating the $DEMO_MODEL model instance"
fi
note "$DEMO_MODEL ($model)${OPENROUTER_API_KEY:+, with a key}"
[[ -n "$OPENROUTER_API_KEY" ]] || note "no OPENROUTER_API_KEY: runs will fail at the model call"

step "Bundles"
catalog=$(curl -sS "$WS/registries/catalog/browse?registry_type=bundles&limit=100" "${H[@]}")
bundles=$(jq -c '[.items[] | select(.registry_name == "system-bundles")]' <<<"$catalog")
[[ $(jq length <<<"$bundles") -gt 0 ]] || fail "no system-bundles in the catalog: import it first (agentarea-api reconcile)"
installed=0; skipped=0; failed=0
while read -r item; do
  name=$(jq -r .name <<<"$item")
  preview=$(curl -sS -X POST "$WS/bundles/analyze" "${H[@]}" -d "$(jq -c '{source: (.spec | tojson)}' <<<"$item")")
  if ! jq -e .bundle >/dev/null <<<"$preview"; then
    note "$name: analyze failed: $(jq -c . <<<"$preview" | cut -c1-200)"; failed=$((failed + 1)); continue
  fi
  if jq -e '.setup[]? | select(.key == "telegram_bot_token")' >/dev/null <<<"$preview" && [[ -z "$DEMO_TELEGRAM_BOT_TOKEN" ]]; then
    note "$name: skipped, needs DEMO_TELEGRAM_BOT_TOKEN"; skipped=$((skipped + 1)); continue
  fi
  body=$(jq -c --arg model "$model" --arg tg "$DEMO_TELEGRAM_BOT_TOKEN" '{
    bundle: .bundle,
    setup_values: (([.setup[]? | select(.default != null) | {(.key): .default}] | add // {})
      + (if any(.setup[]?; .key == "model") then {model: $model} else {} end)
      + (if $tg != "" and any(.setup[]?; .key == "telegram_bot_token") then {telegram_bot_token: $tg} else {} end))
  }' <<<"$preview")
  code=$(curl -sS -o /tmp/demo-install.json -w '%{http_code}' -X POST "$WS/bundles/install" "${H[@]}" -d "$body")
  if [[ "$code" == 2* ]]; then
    note "$name: installed"; installed=$((installed + 1))
  elif grep -qi "already" /tmp/demo-install.json; then
    note "$name: already installed"; skipped=$((skipped + 1))
  else
    note "$name: HTTP $code $(cut -c1-200 /tmp/demo-install.json)"; failed=$((failed + 1))
  fi
done < <(jq -c '.[]' <<<"$bundles")
note "$installed installed, $skipped skipped, $failed failed"
