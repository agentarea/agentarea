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
