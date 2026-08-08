---
title: Deploy with Docker Compose
type: guide
summary: Run the full AgentArea platform on one host with docker-compose.yaml, including the secrets you must set before it will start.
prerequisites:
  - /self-host/requirements
related:
  - /self-host/kubernetes
  - /self-host/configuration
  - /self-host/secrets-backends
  - /self-host/troubleshooting
last_updated: 2026-07-29
---

# Deploy with Docker Compose

Use Compose when the whole platform fits on one host and you do not need
horizontal scaling or rolling updates. It is the fastest path to a running
system and the one the repository exercises most. Use
[Kubernetes](/self-host/kubernetes) instead when you need more than one replica
of anything, or when you want MCP server instances and agent sandboxes confined
by a RuntimeClass — the Compose stack drives MCP containers through the host
Docker socket, which offers no kernel isolation.

Two Compose files sit at the repository root:

| File | Purpose |
|---|---|
| `docker-compose.yaml` | The deployment target. Pulls published images. |
| `docker-compose.dev.yaml` | Development. Bind-mounts source, adds Traefik, Temporal UI, Keto, OpenFGA, Hydra, and Mailpit. |

This guide covers `docker-compose.yaml`.

## Prerequisites

- Docker Engine 20.10 or later with Compose v2 (`docker compose`, not `docker-compose`)
- A clone of the repository — the Compose file bind-mounts `./config/auth/kratos` and `./agentarea-platform/temporal-config`, so it does not run standalone
- Ports 3000, 4433, 7999, 8000 free on the host, plus 5432, 6379, and 9000 if you publish them
- See [requirements](/self-host/requirements) for the full list

## Steps

### 1. Create the environment file

```bash
cd /path/to/agentarea
cp .env.example .env
```

`.env.example` ships working development values. Three of them must be replaced
before this is a deployment rather than a demo.

### 2. Generate the secrets that must not stay at their defaults

`SECRET_MANAGER_ENCRYPTION_KEY` is the Fernet key that encrypts every stored
credential — LLM provider keys, MCP server secrets — in the `agentarea`
database. It must be a valid Fernet key, and it must not change after data
exists, or the ciphertext already written becomes unreadable.

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

`SANDBOX_ACTIVATION_AUTH_SECRET` and `SANDBOX_CLEANUP_AUTH_SECRET` are HMAC
shared secrets between the control plane and the sandbox runner. Both must be at
least 32 bytes. The Compose file declares them with `:?`, so `docker compose`
refuses to start the stack if either is empty rather than falling back to a
default.

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Set all three in `.env`:

```bash
SECRET_MANAGER_ENCRYPTION_KEY=<fernet key from above>
SANDBOX_ACTIVATION_AUTH_SECRET=<48-byte token>
SANDBOX_CLEANUP_AUTH_SECRET=<a different 48-byte token>
POSTGRES_USER=agentarea
POSTGRES_PASSWORD=<a real password>
POSTGRES_DB=agentarea
RUSTFS_ACCESS_KEY=<a real access key>
RUSTFS_SECRET_KEY=<a real secret key>
```

`.env.example` also ships a `KRATOS_JWKS_B64` value with the private key
included. It is a published test key. Anyone can mint tokens your API will
accept. Replace it before exposing the API to a network you do not control.

### 3. Start the stack

```bash
docker compose -f docker-compose.yaml up -d
```

Or, equivalently, `make up` — which runs the same file in the foreground.

Compose brings services up in dependency order:

1. `db` becomes healthy (`pg_isready`), and `rustfs` becomes healthy.
2. `postgres_init` creates the `agentarea`, `temporal`, and `kratos` databases. It is idempotent.
3. `app_migrations` runs `agentarea-api migrate` with working directory `/app/apps/api`, and `kratos-migrate` runs the Kratos schema migration. `rclone-init` creates the two object-storage buckets.
4. `app`, `frontend`, `agentarea-worker`, `agentarea-events`, `agentarea-mcp-manager`, `sandbox-executor`, `temporal`, and `kratos` start.

The one-shot containers (`postgres_init`, `app_migrations`, `kratos-migrate`,
`rclone-init`) exit 0 and stay in `Exited` state. That is the expected result,
not a failure.

`temporal` has a 120-second `start_period` on its health check, and
`agentarea-worker` waits for it. First start therefore takes a couple of minutes
before tasks can run.

### 4. Reach the platform

| Surface | URL |
|---|---|
| Frontend | http://localhost:3000 |
| API and OpenAPI docs | http://localhost:8000/docs |
| MCP Manager | http://localhost:7999 |
| Kratos public API | http://localhost:4433 |

The Compose file publishes no ports for PostgreSQL, Valkey, RustFS, Temporal, or
the event service. They are reachable only on the Compose networks.

## Verify

Check that the long-running services are up and the one-shot jobs completed:

```bash
docker compose -f docker-compose.yaml ps
```

Every one-shot container should show `Exited (0)`. Any other exit code means
that step failed and the services depending on it did not start.

Check the two HTTP health endpoints:

```bash
curl -s http://localhost:8000/health
curl -s http://localhost:7999/health
```

The API returns its status, service name, version, connection health, and a
timestamp:

```json
{"status":"healthy","service":"agentarea-api","version":"0.1.0","connections":{},"timestamp":"..."}
```

Confirm the migrations actually applied, rather than the stack merely being up:

```bash
docker compose -f docker-compose.yaml logs app_migrations
```

Look for `Migrations completed successfully`. `Stamped database to head
revision` is also a success — it means the schema already existed and Alembic
recorded the current head without replaying migrations.

## Troubleshooting

**`docker compose` exits immediately with `SANDBOX_ACTIVATION_AUTH_SECRET must
be set`.** The Compose file uses `${VAR:?message}` for both sandbox secrets, so
an empty value aborts the run rather than starting an unauthenticated sandbox
path. Set both in `.env`.

**The API container restarts in a loop with
`SECRET_MANAGER_ENCRYPTION_KEY environment variable must be set`.** The default
secret backend is `database`, which requires a Fernet key. `SecretManagerFactory`
validates this at construction time and raises, so the process exits at startup
instead of failing later on the first secret read. Generate a key as in step 2.

**`app` never starts and `app_migrations` shows `Exited (1)`.** Read
`docker compose -f docker-compose.yaml logs app_migrations`. The migration
command prints `Migration failed:` followed by the cause. A dirty database — one
with tables from another product but no `provider_specs` table — makes Alembic
apply migrations onto a schema it does not own. See
[database and migrations](/self-host/database-and-migrations).

**The `db` container refuses to start after an upgrade from an older checkout.**
`postgres:18` stores data under `/var/lib/postgresql/<version>/docker`, so the
Compose file mounts `./data/postgres` at `/var/lib/postgresql`, not at the legacy
`/var/lib/postgresql/data`. A data directory laid out for the old mount point
will not start under this file.

**Tasks stay queued and never execute.** `agentarea-worker` waits for
`temporal` to pass its health check, which has a 120-second start period. Check
`docker compose -f docker-compose.yaml logs temporal` and confirm the worker is
running.

**Stopping the stack loses data.** `docker compose down -v` removes volumes. The
platform's data lives in bind mounts under `./data/` (`postgres`, `rustfs`,
`valkey`), so `down -v` does not remove it — but `rm -rf ./data` does. See
[backup and recovery](/self-host/backup-and-recovery).

## Related

- [Requirements](/self-host/requirements)
- [Configuration](/self-host/configuration)
- [Deploy on Kubernetes with Helm](/self-host/kubernetes)
- [Choose a secrets backend](/self-host/secrets-backends)
- [Troubleshoot a self-hosted deployment](/self-host/troubleshooting)
