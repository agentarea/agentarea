# shellcheck shell=sh
# Credential primitives shared by scripts/install.sh (quickstart) and
# scripts/gen-dev-secrets.sh (local development).
#
# Single source of truth on purpose: these generate the keys that authenticate
# every request to the platform, and two drifting copies of that is how a
# published key ends up shipping. Callers must define `fail`.

random_token() {
  bytes="${1:-32}"
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -base64 "$bytes" | tr '+/' '-_' | tr -d '\n'
  elif [ -r /dev/urandom ]; then
    LC_ALL=C tr -dc 'A-Za-z0-9' < /dev/urandom | head -c "$bytes"
  else
    fail "no source of randomness available (need openssl or /dev/urandom); refusing to generate guessable credentials"
  fi
}

# Ory's xchacha20-poly1305 cipher secret must be exactly 32 characters.
random_secret_32() {
  random_token 32 | cut -c1-32
}

fernet_key() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -base64 32 | tr '+/' '-_' | tr -d '\n'
  else
    random_token 44
  fi
}

hex_to_b64url() {
  hex="$1"
  if command -v xxd >/dev/null 2>&1; then
    printf '%s' "$hex" | xxd -r -p | openssl base64 -A | tr '+/' '-_' | tr -d '='
  else
    esc=$(printf '%s' "$hex" | sed 's/../\\x&/g')
    # shellcheck disable=SC2059
    printf "$esc" | openssl base64 -A | tr '+/' '-_' | tr -d '='
  fi
}

# Generates a fresh ES256 keypair. The PRIVATE JWKS is written to $1 — Kratos
# signs tokens with it. The PUBLIC JWKS is printed base64-encoded on stdout for
# KRATOS_JWKS_B64; the backend only ever verifies, so it must not receive `d`.
generate_jwks() {
  jwks_private_path="$1"
  jwks_kid="${2:-agentarea-jwt-key-1}"

  command -v openssl >/dev/null 2>&1 || fail "openssl is required to generate the JWT signing key"

  jwks_tmp_key=$(mktemp)
  openssl ecparam -name prime256v1 -genkey -noout -out "$jwks_tmp_key" 2>/dev/null \
    || fail "openssl could not generate an EC P-256 key"
  jwks_key_text=$(openssl ec -in "$jwks_tmp_key" -text -noout 2>/dev/null) \
    || fail "openssl could not read the generated EC key"
  rm -f "$jwks_tmp_key"

  d_hex=$(printf '%s\n' "$jwks_key_text" | awk '/priv:/{f=1;next} /pub:/{f=0} f' | tr -d ' :\n')
  pub_hex=$(printf '%s\n' "$jwks_key_text" | awk '/pub:/{f=1;next} /ASN1 OID|NIST/{f=0} f' | tr -d ' :\n')

  [ "${#d_hex}" -eq 64 ] || fail "unexpected EC private scalar length (${#d_hex}), refusing to write a malformed JWKS"
  [ "${#pub_hex}" -eq 130 ] || fail "unexpected EC public point length (${#pub_hex}), refusing to write a malformed JWKS"

  x_b64=$(hex_to_b64url "$(printf '%s' "$pub_hex" | cut -c3-66)")
  y_b64=$(hex_to_b64url "$(printf '%s' "$pub_hex" | cut -c67-130)")
  d_b64=$(hex_to_b64url "$d_hex")

  mkdir -p "$(dirname "$jwks_private_path")"
  printf '{"keys":[{"kty":"EC","kid":"%s","use":"sig","alg":"ES256","crv":"P-256","x":"%s","y":"%s","d":"%s"}]}\n' \
    "$jwks_kid" "$x_b64" "$y_b64" "$d_b64" > "$jwks_private_path"
  chmod 600 "$jwks_private_path"

  printf '{"keys":[{"kty":"EC","kid":"%s","use":"sig","alg":"ES256","crv":"P-256","x":"%s","y":"%s"}]}' \
    "$jwks_kid" "$x_b64" "$y_b64" | openssl base64 -A
}

# Every credential the compose files declare with no default, listed once. Both
# callers drive this list, so a key added for one path cannot go missing on the
# other — which is exactly how the sandbox secrets came to block a fresh install
# while the checkout path had them.
MANAGED_SECRET_KEYS='KRATOS_JWKS_B64
KRATOS_SECRETS_COOKIE
KRATOS_SECRETS_CIPHER
HYDRA_SECRETS_SYSTEM
HYDRA_SECRETS_COOKIE
HYDRA_PAIRWISE_SALT
SANDBOX_ACTIVATION_AUTH_SECRET
SANDBOX_CLEANUP_AUTH_SECRET
SANDBOX_FILE_AUTH_SECRET
SANDBOX_CONTROL_AUTH_SECRET
MCP_GATEWAY_AUTH_SECRET'

# $1 key, $2 path receiving the Kratos private JWKS.
secret_value_for() {
  case "$1" in
    KRATOS_JWKS_B64) generate_jwks "$2" ;;
    # HMAC keys, not Ory cipher secrets, so no 32-character constraint. The
    # glob also covers sandbox secrets added later.
    SANDBOX_*_AUTH_SECRET | MCP_GATEWAY_AUTH_SECRET) random_token 32 ;;
    *) random_secret_32 ;;
  esac
}

# A key counts as set only when it has a non-empty value: compose declares these
# as ${VAR:?}, which rejects an empty assignment exactly like a missing one, so
# `KEY=` must not read as "already configured".
env_has_value() {
  [ -f "$1" ] && grep -qE "^$2=." "$1"
}

# Managed keys that $1 does not supply, one per line; empty means nothing to do.
# KRATOS_JWKS_B64 counts as missing when the private half at $2 is gone: the
# variable carries only the public half, so without that file Kratos cannot
# sign however configured the variable looks. $2 is gitignored, so a fresh
# checkout drops it while .env keeps the stale public half.
pending_secret_keys() {
  for _key in $MANAGED_SECRET_KEYS; do
    if ! env_has_value "$1" "$_key"; then
      printf '%s\n' "$_key"
    elif [ "$_key" = KRATOS_JWKS_B64 ] && [ ! -f "$2" ]; then
      printf '%s\n' "$_key"
    fi
  done
}

# Writes the newline-separated keys in $2 into the env file $1, replacing any
# assignment those keys already have and leaving every other line untouched.
# $3 receives the Kratos private JWKS.
write_secret_keys() {
  _env="$1"
  _keys="$2"
  _jwks="$3"
  [ -n "$_keys" ] || return 0

  if [ -f "$_env" ]; then
    _filter=$(printf '%s' "$_keys" | tr '\n' '|' | sed 's/|$//')
    _tmp="$_env.tmp"
    grep -v -E "^($_filter)=" "$_env" > "$_tmp" || true
    mv "$_tmp" "$_env"
  fi

  {
    printf '\n# --- generated credentials, unique to this machine; do not commit ---\n'
    for _key in $_keys; do
      if [ "$_key" = KRATOS_JWKS_B64 ]; then
        printf '# Public half only. Kratos signs with the private half in\n'
        printf '# %s.\n' "$_jwks"
      fi
      printf '%s=%s\n' "$_key" "$(secret_value_for "$_key" "$_jwks")"
    done
  } >> "$_env"

  chmod 600 "$_env"
}
