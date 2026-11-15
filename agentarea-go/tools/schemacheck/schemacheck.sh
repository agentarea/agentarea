#!/usr/bin/env bash
# The goose baselines equal what Alembic builds.
#
#   schemacheck.sh          check: exit non-zero on any difference
#   schemacheck.sh regen    rewrite internal/schema/migrations/00001_baseline.sql and
#                           ../agentarea-enterprise/platform/migrations/00001_baseline.sql first
#
# DB A: `alembic upgrade head` from agentarea-platform/apps/api, then the
# enterprise stream when ../agentarea-enterprise exists. DB B: the goose
# baselines through schema.Migrate. Compared: normalized pg_dump --schema-only,
# every row of every non-empty table (fresh ids and timestamps masked), and
# invalid indexes. Also checked: schema.Migrate records the baseline on DB A
# without changing it, and refuses a database at another Alembic revision.
#
# Needs docker with the local image postgres:18 (never pulled), uv, go.
set -euo pipefail

mode=${1:-check}
case "$mode" in check | regen) ;; *) echo "usage: $0 [check|regen]" >&2; exit 2 ;; esac

GO_DIR=$(cd "$(dirname "$0")/../.." && pwd)
REPO_DIR=$(cd "$GO_DIR/.." && pwd)
API_DIR=$REPO_DIR/agentarea-platform/apps/api
ENT_DIR=$(cd "$REPO_DIR/.." && pwd)/agentarea-enterprise
ENT_MIGRATIONS="$ENT_DIR/platform/migrations"
CONTAINER=aa-go-schema-pg
IMAGE=postgres:18
PORT=55433

docker image inspect "$IMAGE" >/dev/null 2>&1 || { echo "needs the local image $IMAGE; this script never pulls" >&2; exit 1; }

WORK=$(mktemp -d)
cleanup() {
  docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
  rm -rf "$WORK"
}
trap cleanup EXIT

docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
docker run -d --rm --name "$CONTAINER" \
  -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=postgres \
  -e PGDATA=/var/lib/postgresql/data --tmpfs /var/lib/postgresql/data \
  -p "127.0.0.1:$PORT:5432" "$IMAGE" >/dev/null
for _ in $(seq 1 60); do
  docker exec "$CONTAINER" psql -U postgres -h 127.0.0.1 -tAc 'select 1' >/dev/null 2>&1 && break
  sleep 1
done

psql_c() { docker exec -i "$CONTAINER" psql -U postgres -v ON_ERROR_STOP=1 -q "$@"; }
dump() { docker exec "$CONTAINER" pg_dump -U postgres -d "$1" --schema-only --no-owner --no-privileges; }
dsn() { echo "postgres://postgres:postgres@127.0.0.1:$PORT/$1?sslmode=disable"; }
sc() { go -C "$GO_DIR" run ./tools/schemacheck "$@"; }

for db in alembic_a goose_b refused_c; do psql_c -c "CREATE DATABASE $db"; done

enterprise=false
[ -d "$ENT_DIR/agentarea_enterprise/migrations" ] && [ -d "$ENT_MIGRATIONS" ] && enterprise=true

echo "== A: alembic upgrade head (enterprise: $enterprise)"
export AGENTAREA_DB_HOST=127.0.0.1 AGENTAREA_DB_PORT=$PORT AGENTAREA_DB_USER=postgres AGENTAREA_DB_PASSWORD=postgres AGENTAREA_DB_NAME=alembic_a
(cd "$API_DIR" && uv run alembic upgrade head >"$WORK/alembic.log" 2>&1) || { cat "$WORK/alembic.log" >&2; exit 1; }
if $enterprise; then
  # Steps 1, 2, 3 and 5 of agentarea-enterprise-migrate; step 4 (core) ran above.
  (cd "$API_DIR" && PYTHONPATH="$ENT_DIR" uv run python -c '
from sqlalchemy import create_engine
from agentarea_common.config import get_db_settings
from agentarea_enterprise.migrations import cli
with create_engine(get_db_settings().sync_url).connect() as c:
    cli.adopt_ledger(c); cli.release_legacy_core_revision(c); cli.upgrade_enterprise(c)
' >"$WORK/enterprise.log" 2>&1) || { cat "$WORK/enterprise.log" >&2; exit 1; }
fi
dump alembic_a >"$WORK/a.sql"

# The enterprise set lives in the enterprise module; its head is what Alembic reached.
ent_flags=()
if $enterprise; then
  ent_head=$(psql_c -d alembic_a -tAc "SELECT version_num FROM agentarea_enterprise.alembic_version_enterprise")
  ent_flags=(-enterprise-dir "$ENT_MIGRATIONS" -enterprise-head "$ent_head")
fi

if [ "$mode" = regen ]; then
  echo "== regen baselines"
  ent_gen=()
  $enterprise && ent_gen=(-enterprise "$ENT_MIGRATIONS/00001_baseline.sql" -enterprise-head "$ent_head")
  sc gen -dump "$WORK/a.sql" -dsn "$(dsn alembic_a)" \
    -core "$GO_DIR/internal/schema/migrations/00001_baseline.sql" ${ent_gen[@]+"${ent_gen[@]}"}
fi

echo "== B: goose baselines"
sc apply -dsn "$(dsn goose_b)" ${ent_flags[@]+"${ent_flags[@]}"}
dump goose_b >"$WORK/b.sql"

sc normalize -dump "$WORK/a.sql" -dsn "$(dsn alembic_a)" -out "$WORK/a.norm"
sc normalize -dump "$WORK/b.sql" -dsn "$(dsn goose_b)" -out "$WORK/b.norm"
status=0
if ! diff -u "$WORK/a.norm" "$WORK/b.norm" >"$WORK/ab.diff"; then
  echo "FAIL: goose baseline differs from alembic head" >&2
  cat "$WORK/ab.diff" >&2
  status=1
fi
if grep -q '^invalid index' "$WORK/b.norm"; then
  echo "FAIL: the goose baseline leaves invalid indexes:" >&2
  grep '^invalid index' "$WORK/b.norm" >&2
  status=1
fi

echo "== A again: schema.Migrate records the baseline on the Alembic database"
sc apply -dsn "$(dsn alembic_a)" ${ent_flags[@]+"${ent_flags[@]}"}
dump alembic_a >"$WORK/a2.sql"
sc normalize -dump "$WORK/a2.sql" -dsn "$(dsn alembic_a)" -out "$WORK/a2.norm"
if ! diff -u "$WORK/a.norm" "$WORK/a2.norm" >&2; then
  echo "FAIL: recording the baseline changed the Alembic database" >&2
  status=1
fi
recorded=$(psql_c -d alembic_a -tAc "SELECT string_agg(version_id::text, ',' ORDER BY id) FROM public.goose_db_version")
[ "$recorded" = "0,1" ] || { echo "FAIL: core goose versions on A are '$recorded', want 0,1" >&2; status=1; }

echo "== C: another Alembic revision is refused"
psql_c -d refused_c -c "CREATE TABLE alembic_version (version_num varchar(32) PRIMARY KEY); INSERT INTO alembic_version VALUES ('20261110_1100_graph_migrations')"
if sc apply -dsn "$(dsn refused_c)" >"$WORK/c.log" 2>&1; then
  echo "FAIL: a database at 20261110_1100_graph_migrations was migrated" >&2
  status=1
elif ! grep -q "20261110_1100_graph_migrations" "$WORK/c.log"; then
  echo "FAIL: the refusal does not name the revision:" >&2
  cat "$WORK/c.log" >&2
  status=1
fi

if [ $status -eq 0 ]; then
  tables=$(psql_c -d goose_b -tAc "SELECT count(*) FILTER (WHERE n.nspname = 'public'), count(*) FILTER (WHERE n.nspname = 'agentarea_enterprise') FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE c.relkind IN ('r', 'p') AND NOT c.relispartition AND c.relname NOT LIKE 'goose_db_version%'")
  echo "OK: goose baseline equals alembic head (tables public|enterprise, partitions excluded: $tables)"
fi
exit $status
