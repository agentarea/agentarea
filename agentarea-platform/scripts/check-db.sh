#!/usr/bin/env bash
# Everything that needs the real migrated schema: migrations apply to a fresh
# database and roundtrip, then every suite whose rules only SQL can enforce
# (unique constraints, RESTRICT foreign keys, triggers, partial indexes) runs
# against it. Without a database those suites skip, so they live here and not
# in `make test`. Run by CI's migrations-gate; locally: `make db-test-up` from
# the repo root, export what it prints, then `make check-db`.
#
# To add a suite, add it to one of the lists below.
set -euo pipefail

cd "$(dirname "$0")/.."
PLATFORM_DIR=$(pwd)
REPO_DIR=$(cd .. && pwd)

missing=()
for var in POSTGRES_HOST POSTGRES_PORT POSTGRES_USER POSTGRES_PASSWORD POSTGRES_DB; do
  [ -n "${!var:-}" ] || missing+=("$var")
done
if [ ${#missing[@]} -gt 0 ]; then
  echo "check-db needs a disposable Postgres; unset: ${missing[*]}" >&2
  echo "Start one with 'make db-test-up' from the repo root and export the variables it prints." >&2
  exit 1
fi
command -v go >/dev/null || { echo "check-db needs Go for the MCP manager's SQL suites: https://go.dev/doc/install" >&2; exit 1; }

DSN="${POSTGRES_USER}:${POSTGRES_PASSWORD}@${POSTGRES_HOST}:${POSTGRES_PORT}/${POSTGRES_DB}"

# Python suites. Each reads its own *_TEST_DATABASE_URL (asyncpg driver).
#   secrets catalog: a unique constraint decides "create", a RESTRICT FK "delete".
#   provider-secret lifecycle: ordering only real RESTRICT FKs enforce; the
#     mocked unit tests passed while deleting a provider config returned 500.
#   audit: append-only is a trigger refusing UPDATE/DELETE. This connects as a
#     superuser, so a grant-based rule would pass here while enforcing nothing.
#   wallet idempotency: a partial unique index forbids settling a retry twice.
#   wallet ledger: a payment settled before its request failed still counts,
#     and ledger sums are exact because money columns are numeric.
#   model prices: a per-token price survives the numeric column exactly.
#   platform-managed providers: a platform config is readable from every
#     workspace and writable from none, a rule only the WHERE clause enforces.
#   usage events: raw facts are append-only (a trigger) and paging never crosses
#     workspaces.
#   membership backfill: the migration and the reconcile script insert rows with
#     SQL that leans on the (workspace, user) unique constraint and the
#     invitation and outbox tables.
#   catalog browse plans: /explore is only fast while every browse query has an
#     index that serves it, a property of the migrated indexes and the planner.
#   agent presets: presets are a jsonb containment query on catalog tags, and a
#     preset's skill key is matched against hashed catalog names with LIKE.
#   MCP spec list: tenant specs and catalog items are paged, filtered and
#     looked up by id in SQL; the catalog is never materialized per request.
PY_SUITE_ENV=(SECRETS_TEST_DATABASE_URL AUDIT_TEST_DATABASE_URL WALLET_TEST_DATABASE_URL LLM_TEST_DATABASE_URL USAGE_TEST_DATABASE_URL MEMBERSHIP_TEST_DATABASE_URL CATALOG_TEST_DATABASE_URL)
PY_SUITES=(
  libs/secrets/tests/test_catalog_service.py
  libs/llm/tests/test_provider_secret_lifecycle_db.py
  libs/common/tests/test_audit_append_only_db.py
  libs/wallet/tests/test_payment_idempotency_db.py
  libs/wallet/tests/test_payment_ledger_db.py
  libs/llm/tests/test_model_spec_price_precision_db.py
  libs/llm/tests/test_platform_managed_providers_db.py
  libs/common/tests/test_usage_events_db.py
  apps/api/tests/test_membership_backfill_db.py
  libs/registry/tests/test_catalog_browse_plans_db.py
  libs/agents/tests/test_catalog_presets_db.py
  libs/mcp/tests/test_mcp_spec_list_db.py
)

# MCP manager Go SQL: the demand gateway's lifecycle rules, the secret
# resolver's join that keeps one workspace's secrets out of another's
# containers, and the usage store's idempotent, precision-preserving writes.
# MCP_GATEWAY_REQUIRE_DB and USAGE_REQUIRE_DB turn a skipped test into a failure.
GO_PACKAGES=(./internal/mcpgateway/... ./internal/secrets/... ./internal/usage/... ./cmd/mcp-manager/)

# The operator's hand-written provider-config SQL; its unit tests mock the
# connection away, which is how it once named a column no migration created.
OPERATOR_SUITES=(tests/test_provider_config_sql_db.py)

echo "==> alembic upgrade head, then downgrade -1 / upgrade head roundtrip"
(
  cd "$PLATFORM_DIR/apps/api"
  uv run alembic upgrade head
  uv run alembic downgrade -1
  uv run alembic upgrade head
)

echo "==> platform schema-backed suites"
py_env=()
for var in "${PY_SUITE_ENV[@]}"; do
  py_env+=("$var=postgresql+asyncpg://$DSN")
done
env "${py_env[@]}" uv run python -m pytest -v "${PY_SUITES[@]}"

echo "==> MCP manager SQL against the migrated schema"
(
  cd "$REPO_DIR/agentarea-mcp-manager"
  MCP_GATEWAY_TEST_DATABASE_URL="postgres://$DSN?sslmode=disable" MCP_GATEWAY_REQUIRE_DB=1 \
  USAGE_TEST_DATABASE_URL="postgres://$DSN?sslmode=disable" USAGE_REQUIRE_DB=1 \
    go test -v -count=1 "${GO_PACKAGES[@]}"
)

echo "==> operator SQL against the migrated schema"
(
  cd "$REPO_DIR/agentarea-operator"
  OPERATOR_TEST_DATABASE_URL="postgresql://$DSN" OPERATOR_REQUIRE_DB=1 \
    uv run --group dev python -m pytest -v "${OPERATOR_SUITES[@]}"
)
