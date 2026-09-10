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

# `curl | sh` leaves stdin holding the script, so prompts read the terminal
# directly. A provisioning script or a CI job has no terminal at all.
has_tty() {
  [ -r /dev/tty ] && { : < /dev/tty; } 2>/dev/null
}

ask() {
  prompt="$1"
  default="$2"
  if has_tty; then
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

# Idempotent on purpose. Seeds the non-secret configuration when .env is absent,
# then adds any managed credential the file does not already supply, leaving
# every value you have set alone. Re-running the installer over an existing
# install is therefore the upgrade path: a release that starts requiring a new
# secret fills it in instead of leaving the stack unable to boot.
ensure_env() {
  env_file="$AGENTAREA_HOME/.env"
  jwks_file="$AGENTAREA_HOME/config/auth/kratos/jwks.json"

  if [ ! -f "$env_file" ]; then
    postgres_password=$(random_token 24)
    rustfs_secret_key=$(random_token 32)
    secret_key=$(fernet_key)

    cat > "$env_file" <<EOF
VERSION=latest
POSTGRES_USER=postgres
POSTGRES_PASSWORD=$postgres_password
POSTGRES_DB=agentarea
TEMPORAL_DB=temporal
KRATOS_DB=kratos

RUSTFS_ACCESS_KEY=agentarea
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
EOF
    chmod 600 "$env_file"
    say "Created $env_file"
  fi

  pending=$(pending_secret_keys "$env_file" "$jwks_file")
  if [ -z "$pending" ]; then
    say "Credentials in $env_file are complete"
    return
  fi

  write_secret_keys "$env_file" "$pending" "$jwks_file"
  say "Added credentials to $env_file:"
  for key in $pending; do
    say "  $key"
  done
}

install_bundle() {
  mkdir -p "$AGENTAREA_HOME"

  download "docker-compose.yaml" "$AGENTAREA_HOME/docker-compose.yaml"
  download ".env.example" "$AGENTAREA_HOME/.env.example"
  download "config/auth/kratos/kratos.yml" "$AGENTAREA_HOME/config/auth/kratos/kratos.yml"
  download "config/auth/kratos/identity.schema.json" "$AGENTAREA_HOME/config/auth/kratos/identity.schema.json"
  download "config/auth/kratos/oidc.github.jsonnet" "$AGENTAREA_HOME/config/auth/kratos/oidc.github.jsonnet"
  download "config/auth/kratos/oidc.google.jsonnet" "$AGENTAREA_HOME/config/auth/kratos/oidc.google.jsonnet"
  download "agentarea-platform/temporal-config/development-sql.yaml" "$AGENTAREA_HOME/agentarea-platform/temporal-config/development-sql.yaml"
  download "scripts/lib/secrets.sh" "$AGENTAREA_HOME/scripts/lib/secrets.sh"

  # Credential generation and the list of required keys live in one place so the
  # quickstart and the dev bootstrap cannot drift apart.
  # shellcheck source=lib/secrets.sh
  . "$AGENTAREA_HOME/scripts/lib/secrets.sh"

  ensure_env
}

compose() {
  COMPOSE_PROJECT_NAME=agentarea docker compose \
    --env-file "$AGENTAREA_HOME/.env" \
    -f "$AGENTAREA_HOME/docker-compose.yaml" "$@"
}

open_urls() {
  cat <<EOF
AgentArea URLs:
  Web app:       http://localhost:3000
  API:           http://localhost:8000
  API docs:      http://localhost:8000/docs
  MCP manager:   http://localhost:7999
  Kratos public: http://localhost:4433
EOF
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
say "AgentArea runtime bundle is ready in $AGENTAREA_HOME"
say ""
say "Your settings live in .env. Everything else in this directory is managed"
say "by the installer and is replaced when you run it again, which is also how"
say "you pick up a release that requires a new setting."
say ""

if ! have docker; then
  say "Install Docker, then start the stack with:"
  say "  cd $AGENTAREA_HOME && docker compose up -d"
  exit 0
fi

# Starting is the expected next step, so an interactive run defaults to yes. A
# run with no terminal takes the opposite default and requires AGENTAREA_YES=1,
# so piping the installer into another program never launches containers as a
# side effect of installing them.
if [ "${AGENTAREA_YES:-}" = "1" ]; then
  start_now=Y
elif has_tty; then
  start_now=$(ask "Start AgentArea now? [Y/n]" "Y")
else
  start_now=N
fi

case "$start_now" in
  n | N | no | NO)
    say "Skipped startup. Start it with:"
    say "  cd $AGENTAREA_HOME && docker compose up -d"
    ;;
  *)
    say "Starting AgentArea (first run pulls images, which takes a few minutes)..."
    compose up -d
    say ""
    open_urls
    ;;
esac
