#!/usr/bin/env bash
# Regression check for #481: generate_jwks() (scripts/lib/secrets.sh) must
# keep the private Kratos JWKS container-readable and its config/auth
# ancestor host-private. Runs in a scratch dir; needs no Docker.
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
fail() { printf 'error: %s\n' "$*" >&2; exit 1; }
# shellcheck source=lib/secrets.sh
. "$repo_root/scripts/lib/secrets.sh"

scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT
mkdir -p "$scratch/config/auth/kratos"
chmod 755 "$scratch/config/auth/kratos"

generate_jwks "$scratch/config/auth/kratos/jwks.json" >/dev/null

file_mode() { stat -c '%a' "$1" 2>/dev/null || stat -f '%Lp' "$1"; }

jwks_file="$scratch/config/auth/kratos/jwks.json"
mode=$(file_mode "$jwks_file")
echo "jwks.json mode: $mode"
other_bit=$(( 8#$mode % 8 ))
if [ $(( other_bit & 4 )) -eq 0 ]; then
  fail "jwks.json is not world-readable (mode $mode); Kratos reads it as a non-root uid over a bind mount."
fi

auth_dir="$scratch/config/auth"
auth_mode=$(file_mode "$auth_dir")
echo "config/auth mode: $auth_mode"
if [ "$auth_mode" != "700" ]; then
  fail "config/auth must be 700 (host-private), got $auth_mode."
fi

echo "jwks-perms-check passed"
