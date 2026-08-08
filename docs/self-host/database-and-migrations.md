---
title: Run database migrations
type: guide
summary: Apply, inspect, and recover Alembic migrations for the AgentArea schema, on Kubernetes and on Docker Compose.
prerequisites:
  - /self-host/requirements
related:
  - /self-host/kubernetes
  - /self-host/docker-compose
  - /self-host/upgrades
  - /self-host/backup-and-recovery
last_updated: 2026-07-29
---

# Run database migrations

AgentArea's schema is managed by Alembic and applied by the
`agentarea-api migrate` command. Both deployment targets run it automatically
before the API starts, so most of the time there is nothing to do. This guide
covers the cases where there is: inspecting what ran, applying migrations by
hand, and recovering a database that Alembic will not advance.

Migrations run from `agentarea-platform/apps/api`, never from the repository
root. `alembic.ini` sets `script_location = alembic` as a relative path, so
Alembic resolves the migration directory against the working directory. Both the
Kubernetes Job and the Compose service set `working_dir: /app/apps/api` for this
reason.

## Prerequisites

- A reachable PostgreSQL instance with the `agentarea` database created
- For local work: Python 3.12 or later and `uv`, from a clone of the repository
- The same `DATABASE_URL` or `POSTGRES_*` values the platform uses

## Steps

### 1. Understand what runs automatically

| Target | Runs as | Command |
|---|---|---|
| Kubernetes | the `<release>-db-migration` Job, gated on `jobs.dbMigration.enabled` | `agentarea-api migrate` |
| Docker Compose | the `app_migrations` service | `agentarea-api migrate` |

Both are ordered ahead of the API. Compose declares
`app_migrations: condition: service_completed_successfully` as a dependency of
`app`, so a failed migration keeps the API from starting rather than letting it
serve against a stale schema. On Kubernetes the Job has
`ttlSecondsAfterFinished: 300` and disappears five minutes after it succeeds.

`agentarea-api migrate` does more than `alembic upgrade head`:

1. It opens a connection and runs `SELECT 1`, printing `Database connection successful`.
2. It reads the current Alembic revision.
3. If there is no revision **and** the `provider_specs` table exists, it treats the schema as already current and runs `alembic stamp head` instead of replaying migrations. This is the path for a database created by an older bootstrap.
4. If there is no revision and no `provider_specs` table, it runs `alembic upgrade head` from empty.
5. If there is a revision, it runs `alembic upgrade head` normally.

On any exception it prints `Migration failed:` and exits 1.

### 2. Apply migrations by hand

When you need to run them outside the normal startup path — after restoring a
backup, or against an external database the Job cannot reach.

On Kubernetes, run a one-off pod from the API image:

```bash
kubectl run agentarea-migrate --rm -it \
  --namespace agentarea \
  --image=agentarea/agentarea-api:latest \
  --restart=Never \
  --overrides='{"spec":{"containers":[{"name":"agentarea-migrate","image":"agentarea/agentarea-api:latest","workingDir":"/app/apps/api","command":["agentarea-api","migrate"],"envFrom":[{"configMapRef":{"name":"agentarea-env-databasejobs"}}],"env":[{"name":"POSTGRES_USER","valueFrom":{"secretKeyRef":{"name":"agentarea-postgresql-secret","key":"username"}}},{"name":"POSTGRES_PASSWORD","valueFrom":{"secretKeyRef":{"name":"agentarea-postgresql-secret","key":"password"}}}]}]}}'
```

Or re-run the chart's own Job by reinstalling with only that Job enabled.

Under Compose:

```bash
docker compose -f docker-compose.yaml run --rm app_migrations
```

From a clone, against a database you can reach directly:

```bash
cd agentarea-platform/apps/api
uv run alembic upgrade head
```

### 3. Inspect migration state

From `agentarea-platform/apps/api`:

```bash
uv run alembic current      # the revision the database is on
uv run alembic heads        # the revision the code expects
uv run alembic history      # the full chain
uv run alembic branches     # non-empty means a merge is needed
```

The platform also exposes this as a command:

```bash
agentarea-api check-migrations
```

Inside a running container:

```bash
docker compose -f docker-compose.yaml exec -w /app/apps/api app alembic current
```

### 4. Create a migration

Only when changing the schema in code.

```bash
cd agentarea-platform/apps/api
uv run alembic revision --autogenerate -m "add widget table"
```

`alembic.ini` sets
`file_template = %%(year)d%%(month).2d%%(day).2d_%%(hour).2d%%(minute).2d_%%(slug)s`,
so new files are named by ISO-style timestamp — `20260729_1432_add_widget_table.py`.
Do not rename them into any other scheme.

Always read the generated file before committing. Autogenerate does not detect
every change, and it will happily drop a column it does not recognise.

### 5. Know which databases exist

One PostgreSQL instance holds several logical databases. Alembic owns only the
first.

| Database | Owned by | Migrated by |
|---|---|---|
| `agentarea` | the platform | `agentarea-api migrate` (Alembic) |
| `temporal` | Temporal | `temporalio/auto-setup` on start |
| `kratos` | Ory Kratos | the `kratos-migrate` container / Job |
| `openfga` | OpenFGA | the `openfga-migrate` container / Job |
| `keto` | Ory Keto | the `keto-migrate` container / Job |

Under Compose these are created by `postgres_init`, which is idempotent. On
Kubernetes each has its own `create-*-db-job`.

## Verify

Confirm the database is at the revision the code expects — the two commands must
print the same identifier:

```bash
docker compose -f docker-compose.yaml exec -w /app/apps/api app alembic current
docker compose -f docker-compose.yaml exec -w /app/apps/api app alembic heads
```

Check the migration run itself succeeded:

```bash
docker compose -f docker-compose.yaml logs app_migrations
```

Expect `Migrations completed successfully`, or `Stamped database to head
revision` when the schema pre-existed. On Kubernetes:

```bash
kubectl logs -n agentarea -l app.kubernetes.io/component=migration
kubectl get jobs -n agentarea
```

The Job should read `1/1`.

Confirm the schema is actually usable, not merely stamped:

```bash
docker compose -f docker-compose.yaml exec db \
  psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "\dt" | head -20
```

## Troubleshooting

**The migration Job sits in `Init:0/1` and logs `Waiting for database...`.** Its
`wait-for-db` init container polls `nc -z <host> <port>` and never times out.
The host is `global.database.host`, or the bundled PostgreSQL service when that
is empty. Verify the host resolves from inside the namespace and the port is
reachable.

**`Migration failed:` with a `relation already exists` error.** Alembic is
replaying a migration against a schema that already has the object. This happens
when a database has tables but no `alembic_version` row, and the auto-stamp path
did not trigger because `provider_specs` was absent — a "dirty" database, in the
command's own words. Confirm the schema really is current, then stamp it:

```bash
cd agentarea-platform/apps/api
uv run alembic stamp head
```

Stamping tells Alembic the database is current without checking. If the schema
is not in fact current, you have hidden the gap rather than closed it; take a
backup first.

**`Can't locate revision identified by '<hash>'`.** The database records a
revision that does not exist in the image's migration directory — usually a
downgrade to an older image after a newer one migrated, or a branch whose
migration was never merged. Roll forward to the image that contains the
revision. Do not delete the `alembic_version` row to make the error go away; it
strands the schema at an unknown point.

**`alembic branches` returns rows.** Two migrations claim the same parent,
typically from two branches merged without rebasing. Generate a merge revision:

```bash
cd agentarea-platform/apps/api
uv run alembic merge -m "merge heads" <rev1> <rev2>
```

**Migrations work locally but fail in the container with
`FAILED: No 'script_location' key found`.** The command ran from the repository
root. `alembic.ini` uses a relative `script_location`, so the working directory
must be `agentarea-platform/apps/api` (`/app/apps/api` in the image).

**A `helm upgrade` leaves the API running an older schema.** The migration Job
is a normal resource, not a Helm hook — the chart notes this is deliberate, to
avoid a dependency deadlock with the database. It therefore does not block the
Deployment rollout. Check the Job completed before assuming the upgrade is done.
See [upgrades](/self-host/upgrades).

## Related

- [Deploy on Kubernetes with Helm](/self-host/kubernetes)
- [Deploy with Docker Compose](/self-host/docker-compose)
- [Upgrade a deployment](/self-host/upgrades)
- [Back up and restore](/self-host/backup-and-recovery)
