#!/bin/sh
set -eu

AGENTAREA_REF="${AGENTAREA_REF:-main}"
AGENTAREA_HOME="${AGENTAREA_HOME:-$(pwd)/agentarea}"
AGENTAREA_RAW_BASE="${AGENTAREA_RAW_BASE:-https://raw.githubusercontent.com/agentarea/agentarea/$AGENTAREA_REF}"

say() {
  printf '%s\n' "$*"
}

warn() {
  printf 'warning: %s\n' "$*" >&2
}

fail() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

ask() {
  prompt="$1"
  default="$2"
  if [ -r /dev/tty ] && { : < /dev/tty; } 2>/dev/null; then
    printf '%s ' "$prompt" > /dev/tty
    IFS= read -r answer < /dev/tty || answer=""
  else
    answer=""
  fi
  if [ -z "$answer" ]; then
    answer="$default"
  fi
  printf '%s' "$answer"
}

have() {
  command -v "$1" >/dev/null 2>&1
}

confirm_install_directory() {
  say "AgentArea will be installed into:"
  say "  $AGENTAREA_HOME"
  say ""

  answer=$(ask "Continue? [Y/n]" "Y")
  case "$answer" in
    n|N|no|NO)
      say "Install cancelled."
      exit 0
      ;;
  esac
}


download() {
  source_path="$1"
  target_path="$2"
  target_dir=$(dirname "$target_path")
  mkdir -p "$target_dir"
  url="$AGENTAREA_RAW_BASE/$source_path"
  tmp="$target_path.tmp"
  if have curl; then
    curl -fsSL "$url" -o "$tmp" || fail "failed to download $url"
  elif have wget; then
    wget -qO "$tmp" "$url" || fail "failed to download $url"
  else
    fail "curl or wget is required to download the AgentArea runtime bundle"
  fi
  mv "$tmp" "$target_path"
}

write_env_if_missing() {
  env_file="$AGENTAREA_HOME/.env"
  if [ -f "$env_file" ]; then
    say "Keeping existing $env_file"
    return
  fi

  postgres_password=$(random_token 24)
  rustfs_access_key="agentarea"
  rustfs_secret_key=$(random_token 32)
  secret_key=$(fernet_key)
  kratos_cookie_secret=$(random_secret_32)
  kratos_cipher_secret=$(random_secret_32)
  hydra_system_secret=$(random_secret_32)
  hydra_cookie_secret=$(random_secret_32)
  kratos_jwks_public_b64=$(generate_jwks "$AGENTAREA_HOME/config/auth/kratos/jwks.json")

  cat > "$env_file" <<EOF
VERSION=latest
POSTGRES_USER=postgres
POSTGRES_PASSWORD=$postgres_password
POSTGRES_DB=agentarea
TEMPORAL_DB=temporal
KRATOS_DB=kratos

RUSTFS_ACCESS_KEY=$rustfs_access_key
RUSTFS_SECRET_KEY=$rustfs_secret_key
RUSTFS_REGION=us-east-1
DOCUMENTS_BUCKET=documents
ARTIFACTS_BUCKET=artifacts

SECRET_MANAGER_TYPE=database
SECRET_MANAGER_ENCRYPTION_KEY=$secret_key

ORY_BROWSER_URL=http://localhost:4433
API_BROWSER_URL=http://localhost:8000

SMTP_PROTOCOL=smtp
SMTP_HOST=host.docker.internal
SMTP_PORT=1025
SMTP_USERNAME=user
SMTP_PASSWORD=pass
SMTP_FROM_EMAIL=noreply@agentarea.local
SMTP_FROM_NAME=AgentArea
SMTP_SKIP_SSL_VERIFY=true

OIDC_GOOGLE_CLIENT_ID=
OIDC_GOOGLE_CLIENT_SECRET=
OIDC_GITHUB_CLIENT_ID=
OIDC_GITHUB_CLIENT_SECRET=

KRATOS_ISSUER=http://localhost:4433
KRATOS_AUDIENCE=agentarea-api
# Public half of the keypair generated for this install. Kratos signs with the
# private half in config/auth/kratos/jwks.json; the backend only verifies.
KRATOS_JWKS_B64=$kratos_jwks_public_b64

KRATOS_SECRETS_COOKIE=$kratos_cookie_secret
KRATOS_SECRETS_CIPHER=$kratos_cipher_secret
HYDRA_SECRETS_SYSTEM=$hydra_system_secret
HYDRA_SECRETS_COOKIE=$hydra_cookie_secret
EOF
  chmod 600 "$env_file"
  say "Created $env_file"
}

install_bundle() {
  mkdir -p "$AGENTAREA_HOME"

  download "docker-compose.yaml" "$AGENTAREA_HOME/docker-compose.yaml"
  download "deploy/quickstart/agentarea" "$AGENTAREA_HOME/agentarea"
  download ".env.example" "$AGENTAREA_HOME/.env.example"
  download "config/auth/kratos/kratos.yml" "$AGENTAREA_HOME/config/auth/kratos/kratos.yml"
  download "config/auth/kratos/identity.schema.json" "$AGENTAREA_HOME/config/auth/kratos/identity.schema.json"
  download "config/auth/kratos/oidc.github.jsonnet" "$AGENTAREA_HOME/config/auth/kratos/oidc.github.jsonnet"
  download "config/auth/kratos/oidc.google.jsonnet" "$AGENTAREA_HOME/config/auth/kratos/oidc.google.jsonnet"
  download "agentarea-platform/temporal-config/development-sql.yaml" "$AGENTAREA_HOME/agentarea-platform/temporal-config/development-sql.yaml"
  download "scripts/lib/secrets.sh" "$AGENTAREA_HOME/scripts/lib/secrets.sh"

  # Credential generation lives in one place so the quickstart and the dev
  # bootstrap cannot drift apart.
  # shellcheck source=lib/secrets.sh
  . "$AGENTAREA_HOME/scripts/lib/secrets.sh"

  chmod +x "$AGENTAREA_HOME/agentarea"
  write_env_if_missing
}

say "AgentArea quickstart bootstrap"
say "Source: $AGENTAREA_RAW_BASE"
say ""
confirm_install_directory

if ! have docker; then
  warn "Docker was not found. The bundle will be downloaded, but services cannot start until Docker is installed."
fi

install_bundle

say ""
say "AgentArea runtime bundle is ready."
say ""
say "Configuration file:"
say "  $AGENTAREA_HOME/.env"
say ""
say "Next commands:"
say "  $AGENTAREA_HOME/agentarea doctor"
say "  $AGENTAREA_HOME/agentarea pull"
say "  $AGENTAREA_HOME/agentarea up"
say "  $AGENTAREA_HOME/agentarea config"
say ""

start_now=$(ask "Start AgentArea now? [y/N]" "N")
case "$start_now" in
  y|Y|yes|YES)
    "$AGENTAREA_HOME/agentarea" up
    ;;
  *)
    say "Skipped service startup."
    ;;
esac
