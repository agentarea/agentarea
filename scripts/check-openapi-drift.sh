#!/usr/bin/env bash
# Fails when the committed agentarea-webapp/src/api/openapi.json (source of the
# frontend's generated client) or its docs/ copy differs from what the FastAPI
# backend produces. Keys are normalized so only real schema changes count.
set -euo pipefail

cd "$(dirname "$0")/.."
command -v jq >/dev/null || { echo "jq is required: brew install jq / apt-get install jq" >&2; exit 1; }

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

(cd agentarea-platform && uv run python ../scripts/export-openapi.py -o "$tmp/openapi.json")

jq -S . agentarea-webapp/src/api/openapi.json > "$tmp/committed.json"
jq -S . "$tmp/openapi.json" > "$tmp/exported.json"
if ! diff -q "$tmp/committed.json" "$tmp/exported.json" >/dev/null; then
  echo "agentarea-webapp/src/api/openapi.json is out of date with the backend API." >&2
  echo "Fix with the backend on :8000: cd agentarea-webapp && pnpm generate:api" >&2
  diff --unified=3 "$tmp/committed.json" "$tmp/exported.json" | head -100
  exit 1
fi
echo "openapi.json is up to date with the backend"

jq -S . docs/api-reference/openapi.json > "$tmp/docs.json"
if ! diff -q "$tmp/committed.json" "$tmp/docs.json" >/dev/null; then
  echo "docs/api-reference/openapi.json is out of date. Fix with: cd docs && npm run sync:openapi" >&2
  diff --unified=3 "$tmp/committed.json" "$tmp/docs.json" | head -50
  exit 1
fi
echo "docs copy of openapi.json is in sync"
