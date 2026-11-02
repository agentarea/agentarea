#!/usr/bin/env bash
# Replace the local dev stack's state with a snapshot from demo/snapshot.sh.
#
#   make demo-restore SNAPSHOT=path.tar     # the latest one when SNAPSHOT is unset
#
# Everything in the local databases and object store is overwritten. The stack
# is then started again: its migration services bring an older snapshot up to
# the current schema.

set -euo pipefail

COMPOSE=(docker compose -p "${COMPOSE_PROJECT_NAME:-agentarea}" -f docker-compose.dev.yaml)
DB_CONTAINER="${DB_CONTAINER:-agentarea-db-1}"
STORE_CONTAINER="${STORE_CONTAINER:-agentarea-rustfs-1}"
SNAPSHOT="${SNAPSHOT:-$(ls -t "$HOME"/.agentarea/demo/*.tar 2>/dev/null | head -1)}"

[[ -f "$SNAPSHOT" ]] || { echo "no snapshot: pass SNAPSHOT=path.tar" >&2; exit 1; }

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
tar -C "$work" -xf "$SNAPSHOT"
jq -r '"Snapshot of \(.taken_at), commit \(.commit), schema \(.alembic_revision)"' "$work/manifest.json"

if [[ "${YES:-}" != "1" ]]; then
  read -r -p "Overwrite every local database and the object store? [y/N] " answer
  [[ "$answer" == y* || "$answer" == Y* ]] || exit 1
fi

# Nothing may hold a connection while the databases are replaced.
running=$("${COMPOSE[@]}" ps --services --status running | grep -v -x -e db -e rustfs || true)
[[ -z "$running" ]] || "${COMPOSE[@]}" stop $running

for db in $(jq -r '.databases[]' "$work/manifest.json"); do
  printf "  %s\n" "$db"
  docker exec "$DB_CONTAINER" dropdb -U postgres --if-exists --force "$db"
  docker exec "$DB_CONTAINER" createdb -U postgres "$db"
  docker exec -i "$DB_CONTAINER" pg_restore -U postgres -d "$db" --no-owner <"$work/$db.dump"
done

printf "  object store\n"
docker exec "$STORE_CONTAINER" sh -c 'find /data -mindepth 1 -maxdepth 1 -exec rm -rf {} +'
gunzip -c "$work/store.tar.gz" | docker exec -i "$STORE_CONTAINER" tar -C /data -xf -
docker restart "$STORE_CONTAINER" >/dev/null

"${COMPOSE[@]}" up -d
echo "Restored. The stack is starting; its migration services update the schema."
