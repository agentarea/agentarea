#!/usr/bin/env bash
# preflight.sh — run the same checks CI runs, locally, before pushing.
#
# Mirrors:
#   .github/workflows/ci.yml             (Python lint+tests, Go lint+tests, webapp lint+build)
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

# ── 1. Python lint + tests (agentarea-platform) ─────────────────────────────
# Matches CI: `ruff check` + `ruff format --check` + pytest. Pyright is
# declared in pyproject but NOT enforced by CI; it lights up 400+ pre-existing
# triggers/webhook errors. Run it manually if you care:
#   ( cd agentarea-platform && uv run --with pyright pyright )
if ! should_skip python; then
  step "Python lint (ruff check + format)"
  ( cd agentarea-platform && uv run ruff check . )         || fail "ruff check failed"
  ( cd agentarea-platform && uv run ruff format --check . ) || fail "ruff format failed (run: uv run ruff format .)"
  ok "Python lint"

  step "Python tests (unit + functional, mirrors CI)"
  # Mirrors ci.yml: integration tests are excluded by CI too
  ( cd agentarea-platform && uv run pytest tests/unit tests/functional -m "not integration" -q ) \
    || fail "pytest failed"
  ok "Python tests"
fi

# ── 2. Go lint + tests (agentarea-mcp-manager) ──────────────────────────────
if ! should_skip go; then
  step "Go build + vet"
  ( cd agentarea-mcp-manager && go build ./... ) || fail "go build failed"
  ( cd agentarea-mcp-manager && go vet ./... )   || fail "go vet failed"
  ok "Go build + vet"

  if have golangci-lint; then
    step "Go lint (golangci-lint)"
    ( cd agentarea-mcp-manager && golangci-lint run ./... ) || fail "golangci-lint failed"
    ok "golangci-lint"
  else
    printf '\033[33m⚠ golangci-lint not installed — skipping (install: brew install golangci-lint)\033[0m\n'
  fi

  step "Go tests"
  ( cd agentarea-mcp-manager && go test -count=1 ./... ) || fail "go test failed"
  ok "Go tests"
fi

# ── 3. Schema drift (FastAPI -> openapi.json -> docs copy) ──────────────────
if ! should_skip schema; then
  step "OpenAPI schema drift"
  TMP=$(mktemp -d)
  trap 'rm -rf "$TMP"' EXIT
  ( cd agentarea-platform && uv run python ../scripts/export-openapi.py -o "$TMP/openapi.json" ) \
    || fail "OpenAPI export failed"
  jq -S . agentarea-webapp/src/api/openapi.json > "$TMP/committed.json" \
    || fail "could not normalize committed openapi.json"
  jq -S . "$TMP/openapi.json" > "$TMP/exported.json" \
    || fail "could not normalize exported OpenAPI schema"
  if ! diff -q "$TMP/committed.json" "$TMP/exported.json" >/dev/null 2>&1; then
    diff -u "$TMP/committed.json" "$TMP/exported.json" | head -100
    fail "openapi.json is out of date — run: cd agentarea-webapp && pnpm generate:api"
  fi
  jq -S . docs/api-reference/openapi.json > "$TMP/docs.json" \
    || fail "could not normalize docs OpenAPI schema"
  if ! diff -q "$TMP/committed.json" "$TMP/docs.json" >/dev/null 2>&1; then
    diff -u "$TMP/committed.json" "$TMP/docs.json" | head -50
    fail "docs OpenAPI copy is out of date — run: cd docs && npm run sync:openapi"
  fi
  ok "Schema drift"
fi

# ── 3b. Webapp lint + build (mirrors webapp-lint, webapp-build, frontend-integration) ──
if ! should_skip webapp; then
  if have pnpm; then
    step "Webapp lint (pnpm run lint)"
    ( cd agentarea-webapp && pnpm install --frozen-lockfile >/dev/null ) \
      || fail "pnpm install failed"
    ( cd agentarea-webapp && pnpm run lint ) || fail "webapp lint failed"
    ok "Webapp lint"

    step "Webapp packages build (elements-react)"
    ( cd agentarea-webapp/packages/elements-react && npm run build >/dev/null ) \
      || fail "elements-react build failed"
    ok "elements-react"

    step "Webapp build (pnpm run build, includes type-check)"
    ( cd agentarea-webapp && pnpm run build >/dev/null ) \
      || fail "webapp build failed (type errors block CI even though type-check is warn-only)"
    ok "Webapp build"
  else
    printf '\033[33m⚠ pnpm not installed — skipping webapp build (install: npm i -g pnpm@9)\033[0m\n'
  fi
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
