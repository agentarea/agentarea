#!/usr/bin/env bash
# preflight.sh — run the same checks CI runs, locally, before pushing.
#
# Stacks call the same entrypoints CI does (make check / pnpm run check*).
# Mirrors:
#   .github/workflows/ci.yml             (platform, Go, webapp)
#   .github/workflows/schema-check.yml   (backend -> openapi.json -> docs drift)
#   .github/workflows/frontend-integration.yml (elements-react build + webapp build)
#   .github/workflows/check-helm-docs.yml (Helm chart README)
#   .github/workflows/validate-env-templates.yml (Helm env tpl drift)
#
# Each check is independent — failure prints how to fix and aborts.
# Set SKIP=schema,webapp,helm-docs,... to skip groups.

set -euo pipefail

cd "$(dirname "$0")/.."
ROOT=$(pwd)

SKIP="${SKIP:-}"
should_skip() {
  case ",${SKIP}," in *",$1,"*) return 0 ;; *) return 1 ;; esac
}

step() { printf '\n\033[1;34m▸ %s\033[0m\n' "$1"; }
ok()   { printf '\033[32m✓ %s\033[0m\n' "$1"; }
fail() { printf '\033[31m✗ %s\033[0m\n' "$1"; exit 1; }

# Track tool availability
have() { command -v "$1" >/dev/null 2>&1; }

# ── 1. Platform (lint + tests + migration heads) ────────────────────────────
if ! should_skip python; then
  step "Platform check (make -C agentarea-platform check)"
  make -C agentarea-platform check || fail "platform check failed"
  ok "Platform"
fi

# ── 2. Go (build + tests + golangci-lint) ───────────────────────────────────
if ! should_skip go; then
  step "Go check (mcp-manager, event-service)"
  make -C agentarea-mcp-manager check   || fail "mcp-manager check failed"
  make -C agentarea-event-service check || fail "event-service check failed"
  ok "Go"
fi

# ── 3. Schema drift (FastAPI -> openapi.json -> docs copy) ──────────────────
if ! should_skip schema; then
  step "OpenAPI schema drift"
  bash scripts/check-openapi-drift.sh || fail "OpenAPI schema drift"
  ok "Schema drift"
fi

# ── 3b. Webapp (lint, types, tests, client drift, build) ────────────────────
if ! should_skip webapp; then
  have pnpm || fail "pnpm is required (install: npm i -g pnpm@9) or SKIP=webapp"
  step "Webapp check"
  ( cd agentarea-webapp && pnpm install --frozen-lockfile >/dev/null ) \
    || fail "pnpm install failed"
  pnpm -C agentarea-webapp run check             || fail "webapp check failed"
  pnpm -C agentarea-webapp run check:integration || fail "webapp build checks failed"
  ok "Webapp"
fi

# ── 4. Env templates (Helm config drift) ────────────────────────────────────
if ! should_skip env-tpl; then
  step "Env templates"
  python3 scripts/generate_env_tpls.py || fail "generate_env_tpls.py failed"
  if ! git diff --quiet -- charts/agentarea/templates/configs; then
    git status --porcelain charts/agentarea/templates/configs
    fail "Env templates out of date — review and commit charts/agentarea/templates/configs"
  fi
  ok "Env templates"
fi

# ── 5. Helm chart README (helm-docs) ────────────────────────────────────────
if ! should_skip helm-docs; then
  step "Helm chart README (helm-docs)"
  if have helm-docs; then
    helm-docs --chart-search-root charts/agentarea --sort-values-order file >/dev/null \
      || fail "helm-docs failed"
    if ! git diff --quiet charts/agentarea/README.md; then
      fail "charts/agentarea/README.md is outdated — run helm-docs and commit"
    fi
    ok "Helm chart README"
  else
    printf '\033[33m⚠ helm-docs not installed — skipping (install: brew install norwoodj/tap/helm-docs)\033[0m\n'
  fi
fi

# ── 6. Helm chart lint ──────────────────────────────────────────────────────
if ! should_skip helm-lint; then
  step "Helm chart lint"
  if have helm; then
    helm lint charts/agentarea >/dev/null || fail "helm lint failed"
    ok "Helm chart lint"
  else
    printf '\033[33m⚠ helm not installed — skipping\033[0m\n'
  fi
fi

printf '\n\033[1;32m✓ All preflight checks passed — safe to push.\033[0m\n'
