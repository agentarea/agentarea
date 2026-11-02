#!/usr/bin/env bash
# Save the whole local dev stack's state into one file.
#
#   make demo-snapshot [SNAPSHOT=path.tar]
#
# Every database of the dev Postgres (the platform, its authorization graph,
# identities, OAuth and Temporal), so users, permissions and schedules stay
# consistent with the data, plus the rustfs object store (files, artifacts).
# `make demo-restore` puts it back and lets the migrations bring it up to date.

set -euo pipefail

DB_CONTAINER="${DB_CONTAINER:-agentarea-db-1}"
STORE_CONTAINER="${STORE_CONTAINER:-agentarea-rustfs-1}"
DATABASES=(agentarea kratos openfga hydra temporal temporal_visibility)
SNAPSHOT="${SNAPSHOT:-$HOME/.agentarea/demo/agentarea-demo-$(date +%Y%m%d-%H%M%S).tar}"

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

for db in "${DATABASES[@]}"; do
  printf "  %s\n" "$db"
  docker exec "$DB_CONTAINER" pg_dump -U postgres -Fc "$db" >"$work/$db.dump"
done
printf "  object store\n"
docker exec "$STORE_CONTAINER" tar -C /data -cf - . >"$work/store.tar"

jq -n --arg at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --arg commit "$(git rev-parse --short HEAD)" \
  --arg revision "$(docker exec "$DB_CONTAINER" psql -U postgres -d agentarea -tAc 'SELECT version_num FROM alembic_version')" \
  --argjson databases "$(printf '%s\n' "${DATABASES[@]}" | jq -R . | jq -s .)" \
  '{taken_at: $at, commit: $commit, alembic_revision: $revision, databases: $databases}' >"$work/manifest.json"

mkdir -p "$(dirname "$SNAPSHOT")"
tar -C "$work" -cf "$SNAPSHOT" .
printf "Saved %s (%s)\n" "$SNAPSHOT" "$(du -h "$SNAPSHOT" | cut -f1)"
