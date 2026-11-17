#!/bin/sh
# The behaviour-suite stack: the infrastructure services of
# docker-compose.dev.yaml under project aa-suite with compose.yaml on top (own
# volumes, host ports 57000-57999, local images only), the goose baseline, the
# suite's catalog rows (test/suite/models/seed.sql), and `agentarea serve`,
# `agentarea worker` and `agentarea events` built from agentarea-go on the host.
#
#   stack.sh up                 start services, migrate, seed, start the roles, wait for /health
#   stack.sh down               stop the roles, delete containers, volumes and .state
#   stack.sh env                print the exports a suite run needs
#   stack.sh test [go test args...]
#                               run the suites (default ./test/suite/...)
#   stack.sh config | ps | logs [svc]
#                               docker compose config / ps / logs
set -eu

here=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
repo=$(CDPATH='' cd -- "$here/../../.." && pwd)
gomod="$repo/agentarea-go"
state="$here/.state"
project=aa-suite

api_port=57900
db_port=57432
worker_health_port=57881
events_port=57882

fail() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

# The dev file interpolates many ${VAR:-default}; a value exported in the
# caller's shell (TEMPORAL_ADDRESS=localhost:7233, a dev AGENTAREA_* ...) would
# win over the env file, so compose runs with a clean environment.
compose() {
  env -i PATH="$PATH" HOME="$HOME" \
    ${DOCKER_HOST:+DOCKER_HOST="$DOCKER_HOST"} \
    ${DOCKER_CONTEXT:+DOCKER_CONTEXT="$DOCKER_CONTEXT"} \
    ${DOCKER_CONFIG:+DOCKER_CONFIG="$DOCKER_CONFIG"} \
    docker compose -p "$project" --project-directory "$repo" \
    -f "$repo/docker-compose.dev.yaml" -f "$here/compose.yaml" \
    --env-file "$state/suite.env" "$@"
}

prepare_state() {
  [ -f "$state/suite.env" ] && return 0
  # shellcheck source=/dev/null
  . "$repo/scripts/lib/secrets.sh"
  mkdir -p "$state/kratos"
  cp "$repo/config/auth/kratos/kratos.yml" "$repo/config/auth/kratos/identity.schema.json" \
    "$repo/config/auth/kratos/"oidc.*.jsonnet "$state/kratos/"
  jwks_public=$(generate_jwks "$state/kratos/jwks.json")
  db_password=$(random_token 24)
  fga_key=$(random_secret_32)
  fernet=$(fernet_key)
  rustfs_access=suite$(random_secret_32 | tr -dc 'a-zA-Z0-9' | cut -c1-12)
  rustfs_secret=$(random_token 24)
  # Compose interpolates the whole dev file, so the variables of services this
  # stack does not start (the app containers) are set too.
  cat > "$state/suite.env" <<EOF
AGENTAREA_DB_USER=postgres
AGENTAREA_DB_PASSWORD=$db_password
AGENTAREA_DB_NAME=agentarea
OPENFGA_AUTHN_PRESHARED_KEY=$fga_key
AGENTAREA_DB_TENANT_SCOPE=enforce
AGENTAREA_SECRET_ENCRYPTION_KEY=$fernet
AGENTAREA_SANDBOX_ACTIVATION_SECRET=$(random_token 32)
AGENTAREA_SANDBOX_CLEANUP_SECRET=$(random_token 32)
AGENTAREA_SANDBOX_FILE_SECRET=$(random_token 32)
AGENTAREA_SANDBOX_CONTROL_SECRET=$(random_token 32)
AGENTAREA_MCP_GATEWAY_SECRET=$(random_token 32)
KRATOS_SECRETS_COOKIE=$(random_secret_32)
KRATOS_SECRETS_CIPHER=$(random_secret_32)
HYDRA_SECRETS_SYSTEM=$(random_secret_32)
HYDRA_SECRETS_COOKIE=$(random_secret_32)
HYDRA_PAIRWISE_SALT=$(random_secret_32)
RUSTFS_ACCESS_KEY=$rustfs_access
RUSTFS_SECRET_KEY=$rustfs_secret
RUSTFS_REGION=us-east-1
DOCUMENTS_BUCKET=documents
ARTIFACTS_BUCKET=artifacts
SMTP_HOST=mailpit
SMTP_PORT=1025
SMTP_USERNAME=suite
SMTP_PASSWORD=suite
SMTP_PROTOCOL=smtp
SMTP_FROM_EMAIL=noreply@suite.local
SMTP_FROM_NAME=AgentArea
SMTP_SKIP_SSL_VERIFY=true
SMTP_DISABLE_STARTTLS=true
EOF
  chmod 600 "$state/suite.env"

  # The environment of the agentarea roles on the host. Runs call the suite's
  # fake model provider on loopback (models writes it as localhost, which
  # resolves to ::1 too), which the private allowlist admits. No
  # sandbox manager runs here: AGENTAREA_MCP_MANAGER_URL names a port nothing
  # listens on, so a sandbox execution or MCP Events poll fails when used.
  cat > "$state/go.env" <<EOF
HOST=127.0.0.1
PORT=$api_port
AGENTAREA_DB_HOST=localhost
AGENTAREA_DB_PORT=$db_port
AGENTAREA_DB_USER=postgres
AGENTAREA_DB_PASSWORD=$db_password
AGENTAREA_DB_NAME=agentarea
AGENTAREA_REDIS_URL=redis://localhost:57379
AGENTAREA_EVENT_NAMESPACE=agentarea
AGENTAREA_SECRET_ENCRYPTION_KEY=$fernet
AGENTAREA_AUTH_JWKS_B64=$jwks_public
AGENTAREA_AUTH_ISSUER=http://localhost:4433
AGENTAREA_AUTH_AUDIENCE=agentarea-api
AGENTAREA_AUTH_KRATOS_ADMIN_URL=http://localhost:57434
AGENTAREA_AUTH_HYDRA_URL=http://localhost:57444
AGENTAREA_AUTH_HYDRA_ADMIN_URL=http://localhost:57445
AGENTAREA_AUTHZ_BACKEND=openfga
AGENTAREA_AUTHZ_FGA_URL=http://localhost:57088
AGENTAREA_AUTHZ_FGA_STORE_NAME=agentarea
AGENTAREA_AUTHZ_FGA_API_TOKEN=$fga_key
AGENTAREA_AUTHZ_FGA_BOOTSTRAP=true
AGENTAREA_AUTHZ_FGA_APPLY_MODEL=true
AGENTAREA_MCP_BACKEND=docker
AGENTAREA_MCP_NETWORK=${project}_mcp-network
AGENTAREA_MCP_MANAGER_URL=http://localhost:57910
AGENTAREA_MCP_GATEWAY_SECRET=$(sed -n 's/^AGENTAREA_MCP_GATEWAY_SECRET=//p' "$state/suite.env")
AGENTAREA_MCP_LEASE_TTL=30s
AGENTAREA_MCP_STARTUP_TIMEOUT=120s
AGENTAREA_MCP_IDLE_TIMEOUT=0
AGENTAREA_MCP_SWEEP_INTERVAL=30s
AGENTAREA_HTTP_PRIVATE_ALLOWLIST=127.0.0.0/8,::1/128
AGENTAREA_S3_ENDPOINT=http://localhost:57090
AGENTAREA_S3_PUBLIC_ENDPOINT=http://localhost:57090
AGENTAREA_S3_ACCESS_KEY=$rustfs_access
AGENTAREA_S3_SECRET_KEY=$rustfs_secret
AGENTAREA_S3_REGION=us-east-1
AGENTAREA_S3_BUCKET=documents
AGENTAREA_S3_ARTIFACTS_BUCKET=artifacts
AGENTAREA_API_URL=http://localhost:$api_port
AGENTAREA_TEMPORAL_QUEUE=agent-tasks
TEMPORAL_ADDRESS=127.0.0.1:57233
TEMPORAL_NAMESPACE=default
AGENTAREA_WORKER_HEALTH_PORT=$worker_health_port
AGENTAREA_ANALYTICS_ENABLED=false
EOF
  chmod 600 "$state/go.env"
}

wait_http() {
  url=$1
  deadline=$(($(date +%s) + ${2:-300}))
  until curl -fsS -o /dev/null "$url" 2>/dev/null; do
    [ "$(date +%s)" -lt "$deadline" ] || return 1
    sleep 2
  done
}

services="db postgres_init valkey rustfs bucket-init temporal temporal-namespace kratos hydra openfga mailpit"

db_url() {
  password=$(sed -n 's/^AGENTAREA_DB_PASSWORD=//p' "$state/go.env")
  printf 'postgres://postgres:%s@localhost:%s/agentarea?sslmode=disable' "$password" "$db_port"
}

# Every goose migration through `agentarea migrate`, retried until the database answers.
migrate() {
  deadline=$(($(date +%s) + 120))
  until (set -a; . "$state/go.env"; set +a; "$state/agentarea" migrate) >"$state/migrate.log" 2>&1; do
    [ "$(date +%s)" -lt "$deadline" ] || { cat "$state/migrate.log" >&2; return 1; }
    sleep 2
  done
}

# seed applies the catalog rows the stack's missing catalog reconcile would bring.
seed() {
  compose exec -T db psql -v ON_ERROR_STOP=1 -q -U postgres -d agentarea < "$gomod/test/suite/models/seed.sql"
  compose exec -T db psql -v ON_ERROR_STOP=1 -q -U postgres -d agentarea < "$gomod/test/suite/catalog/seed.sql"
}

roles="serve worker events"

# start runs `agentarea <role>` in the background with go.env.
start() {
  role=$1
  (
    set -a
    # shellcheck source=/dev/null
    . "$state/go.env"
    set +a
    # events serves its health on HOST:PORT, which serve already holds.
    if [ "$role" = events ]; then
      PORT=$events_port
    fi
    nohup "$state/agentarea" "$role" > "$state/$role.log" 2>&1 &
    echo $! > "$state/$role.pid"
  )
}

running() {
  [ -f "$state/$1.pid" ] && kill -0 "$(cat "$state/$1.pid")" 2>/dev/null
}

# stop signals the role and waits for it to exit, so a restart can bind its port.
stop() {
  if running "$1"; then
    kill "$(cat "$state/$1.pid")" 2>/dev/null || true
    deadline=$(($(date +%s) + 60))
    while running "$1"; do
      [ "$(date +%s)" -lt "$deadline" ] || fail "agentarea $1 did not exit"
      sleep 1
    done
  fi
  rm -f "$state/$1.pid"
}

cmd_up() {
  prepare_state
  # Every started service is pull_policy: never, so a missing image fails here.
  # shellcheck disable=SC2086 # $services is a word list.
  compose up -d --no-build $services
  (cd "$gomod" && go build -o "$state/agentarea" ./cmd/agentarea) || fail "go build failed"
  migrate || fail "agentarea migrate failed (log: $state/migrate.log)"
  seed || fail "the suite catalog rows did not apply"
  # The worker gives up on a Temporal that is not serving yet; the namespace
  # job finishes once it is.
  deadline=$(($(date +%s) + 180))
  until [ "$(compose ps -a --format '{{.State}} {{.ExitCode}}' temporal-namespace 2>/dev/null)" = "exited 0" ]; do
    [ "$(date +%s)" -lt "$deadline" ] || fail "the Temporal namespace was not registered"
    sleep 2
  done
  for role in $roles; do
    stop "$role"
    start "$role"
  done
  wait_http "http://localhost:$api_port/health" 60 ||
    { cat "$state/serve.log" >&2; fail "agentarea serve did not answer /health on :$api_port"; }
  wait_http "http://localhost:$worker_health_port/readyz" 60 ||
    { cat "$state/worker.log" >&2; fail "agentarea worker did not answer /readyz on :$worker_health_port"; }
  wait_http "http://localhost:$events_port/readyz" 60 ||
    { cat "$state/events.log" >&2; fail "agentarea events did not answer /readyz on :$events_port"; }
  sleep 3
  for role in $roles; do
    running "$role" || { cat "$state/$role.log" >&2; fail "agentarea $role exited"; }
  done
  wait_http "http://localhost:57433/health/ready" 120 || fail "Kratos public not ready on :57433"
  wait_http "http://localhost:57434/admin/health/ready" 120 || fail "Kratos admin not ready on :57434"
  printf 'suite stack up: agentarea serve http://localhost:%s\n' "$api_port"
}

cmd_down() {
  for role in $roles; do
    stop "$role"
  done
  if [ -f "$state/suite.env" ]; then
    compose down -v --remove-orphans
  fi
  rm -rf "$state"
}

cmd_env() {
  cat <<EOF
export BASE_URL=http://localhost:$api_port
export SUITE_KRATOS_PUBLIC_URL=http://localhost:57433
export SUITE_KRATOS_ADMIN_URL=http://localhost:57434
EOF
}

cmd_test() {
  eval "$(cmd_env)"
  if [ $# -eq 0 ]; then
    set -- ./test/suite/...
  fi
  cd "$gomod"
  exec go test -tags suite -count=1 "$@"
}

case "${1:-}" in
  up) cmd_up ;;
  down) cmd_down ;;
  env) cmd_env ;;
  test) shift; cmd_test "$@" ;;
  config) prepare_state; compose config ;;
  ps) compose ps -a ;;
  logs) shift; compose logs --no-color "$@" ;;
  *) fail "usage: stack.sh up|down|env|test [go test args]|config|ps|logs [service]" ;;
esac
