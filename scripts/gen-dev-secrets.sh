#!/bin/sh
# Generates the local development credentials that docker-compose.yaml and
# docker-compose.dev.yaml require. Nothing here ships in the repository: every
# value is unique to your machine, which is why the compose files fail hard when
# they are missing.
#
# Usage:  ./scripts/gen-dev-secrets.sh [--force]
#
# Without --force the script tops up only the keys that are missing or empty and
# leaves existing values alone, so running it after a compose upgrade cannot
# silently rotate the secrets your running stack already depends on. The key
# list and the generation itself live in lib/secrets.sh, shared with the
# quickstart installer.
set -eu

fail() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

repo_root=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
# shellcheck source=lib/secrets.sh
. "$repo_root/scripts/lib/secrets.sh"

env_file="$repo_root/.env"
jwks_file="$repo_root/config/auth/kratos/jwks.json"

if [ "${1:-}" = "--force" ]; then
  pending="$MANAGED_SECRET_KEYS"
else
  pending=$(pending_secret_keys "$env_file" "$jwks_file")
fi

if [ -z "$pending" ]; then
  printf 'Development secrets already present in %s\n' "$env_file"
  printf 'Re-run with --force to replace them (this invalidates existing sessions).\n'
  exit 0
fi

if [ -f "$env_file" ]; then
  cp "$env_file" "$env_file.bak"
  printf 'Backed up existing env to %s.bak\n' "$env_file"
fi

write_secret_keys "$env_file" "$pending" "$jwks_file"

printf 'Wrote development secrets to %s:\n' "$env_file"
for key in $pending; do
  printf '  %s\n' "$key"
done
if printf '%s\n' "$pending" | grep -q '^KRATOS_JWKS_B64$'; then
  printf 'Wrote Kratos signing key to %s (mode 600, gitignored)\n' "$jwks_file"
fi
