#!/usr/bin/env bash
# test-docx-skill-e2e.sh — runs the docx skill+sandbox integration test.
#
# Prerequisites:
#   - Full docker-compose dev stack must be up (make up-dev). Specifically:
#     backend on :8000, mcp-manager on :7999, kratos on :4433/:4434.
#   - python-docx installed in the agentarea-platform uv venv.
#
# Usage:
#   ./scripts/test-docx-skill-e2e.sh
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT=$(pwd)

step() { printf '\n\033[1;34m> %s\033[0m\n' "$1"; }
ok()   { printf '\033[32m  PASS: %s\033[0m\n' "$1"; }
fail() { printf '\033[31m  FAIL: %s\033[0m\n' "$1"; exit 1; }

step "Checking required env vars"
if [[ -z "${DOCX_E2E_OPENROUTER_KEY:-}" ]]; then
  fail "DOCX_E2E_OPENROUTER_KEY is not set. Export your OpenRouter API key first, e.g. 'export DOCX_E2E_OPENROUTER_KEY=sk-or-v1-...'"
fi
ok "DOCX_E2E_OPENROUTER_KEY present"

step "Checking docker-compose stack health"
if ! curl -sf http://localhost:8000/health >/dev/null; then
  fail "backend at http://localhost:8000/health is not reachable. Run 'make up-dev' first."
fi
ok "backend healthy"

if ! curl -sf http://localhost:7999/health >/dev/null; then
  fail "mcp-manager at http://localhost:7999/health is not reachable."
fi
ok "mcp-manager healthy"

if ! curl -sf http://localhost:4434/admin/identities >/dev/null; then
  fail "kratos admin at http://localhost:4434 is not reachable."
fi
ok "kratos admin reachable"

step "Running docx skill e2e test"
cd "$ROOT/agentarea-platform"
exec uv run pytest -m integration tests/e2e/api/test_docx_skill_integration.py -v -s "$@"
