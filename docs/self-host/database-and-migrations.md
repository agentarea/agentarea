---
title: Run database migrations
type: guide
description: "Apply, inspect, and recover the AgentArea schema migrations, on Kubernetes and on Docker Compose."
prerequisites:
  - /self-host/requirements
related:
  - /self-host/kubernetes
  - /self-host/docker-compose
  - /self-host/upgrades
  - /self-host/backup-and-recovery
last_updated: 2026-11-17
---

AgentArea's schema is a set of goose migrations embedded in the platform binary
and applied by `agentarea migrate`. Both deployment targets run it automatically
before the API starts, so most of the time there is nothing to do. This guide
covers the cases where there is: inspecting what ran, applying migrations by
hand, and recovering a database the command refuses to advance.

The migrations continue the history the earlier Python platform kept with
Alembic: the first file, `00001_baseline.sql`, is the schema at the last Alembic
revision. A database that Alembic brought to that revision is adopted as is; one
at any other Alembic revision is refused.

## Prerequisites

<Info>
- A reachable PostgreSQL instance with the `agentarea` database created
- The same `AGENTAREA_DB_*` values the platform uses
- For local work: Go, from a clone of the repository
</Info>

## Steps

<Steps titleSize="h3">
  <Step title="Understand what runs automatically">
    | Target | Runs as | Command |
    |---|---|---|
    | Kubernetes | the `<release>-db-migration` Job, gated on `jobs.dbMigration.enabled` | `agentarea migrate` |
    | Docker Compose | the `app_migrations` service | `agentarea migrate` |

    Both are ordered ahead of the API. Compose declares
    `app_migrations: condition: service_completed_successfully` as a dependency of
    `app`, so a failed migration keeps the API from starting rather than letting it
    serve against a stale schema. On Kubernetes the Job has
    `ttlSecondsAfterFinished: 300` and disappears five minutes after it succeeds.

    `agentarea migrate` brings each migration set to its latest version: the core
    set (`public.goose_db_version`), then the set of each extension the build
    carries (the enterprise edition adds its own, in the `agentarea_enterprise`
    schema). For each set, under an advisory lock:

    1. If its Alembic version table names the last Alembic revision and goose has no version table yet, the baseline is recorded as applied without running.
    2. If its Alembic version table names any other revision, it stops with an error naming that revision.
    3. If the schema holds no relation, the baseline runs, then every later file.
    4. If the schema holds relations but neither version table, it stops rather than migrate an unknown schema.

    Then it applies the pending authorization-graph migrations. On any error it
    logs it and exits non-zero.
  </Step>

  <Step title="Apply migrations by hand">
    When you need to run them outside the normal startup path — after restoring a
    backup, or against an external database the Job cannot reach.

    On Kubernetes, run a one-off pod from the platform image:

    ```bash
    kubectl run agentarea-migrate --rm -it \
      --namespace agentarea \
      --image=agentarea/agentarea-platform:latest \
      --restart=Never \
      --overrides='{"spec":{"containers":[{"name":"agentarea-migrate","image":"agentarea/agentarea-platform:latest","command":["agentarea","migrate"],"envFrom":[{"configMapRef":{"name":"agentarea-env-databasejobs"}}],"env":[{"name":"AGENTAREA_DB_USER","valueFrom":{"secretKeyRef":{"name":"agentarea-postgresql-secret","key":"username"}}},{"name":"AGENTAREA_DB_PASSWORD","valueFrom":{"secretKeyRef":{"name":"agentarea-postgresql-secret","key":"password"}}}]}]}}'
    ```

    A database whose authorization graph has pending migrations also needs the
    `AGENTAREA_AUTHZ_*` values the chart's Job passes. Re-running the chart's own
    Job (reinstalling with only that Job enabled) carries them.

    Under Compose:

    ```bash
    docker compose -f docker-compose.yaml run --rm app_migrations
    ```

    From a clone, against a database you can reach directly:

    ```bash
    cd agentarea-go
    go run ./cmd/agentarea migrate
    ```
  </Step>

  <Step title="Inspect migration state">
    ```bash
    agentarea check-migrations
    ```

    prints each set's applied and latest version and exits non-zero when one is
    behind. `agentarea validate` loads the configuration, reaches the database and
    reports the same. Inside a running container:

    ```bash
    docker compose -f docker-compose.yaml exec app agentarea check-migrations
    ```
  </Step>

  <Step title="Create a migration">
    Only when changing the schema in code. Add the next numbered file to
    `agentarea-go/internal/schema/migrations/`, for example
    `00005_add_widget_table.sql`, with goose `-- +goose Up` and `-- +goose Down`
    sections. Files are embedded in the binary at build time.
  </Step>

  <Step title="Know which databases exist">
    One PostgreSQL instance holds several logical databases. The platform's
    migrations own only the first.

    | Database | Owned by | Migrated by |
    |---|---|---|
    | `agentarea` | the platform | `agentarea migrate` (goose) |
    | `temporal`, `temporal_visibility` | Temporal | `temporal-sql-tool` (`temporalio/admin-tools`): the `temporal-schema` container under Compose, the Temporal pod's `schema` init container on Kubernetes |
    | `kratos` | Ory Kratos | the `kratos-migrate` container / Job |
    | `openfga` | OpenFGA | the `openfga-migrate` container / Job |

    Under Compose these are created by `postgres_init`, which is idempotent. On
    Kubernetes each has its own `create-*-db-job`.
  </Step>
</Steps>

## Verify

Confirm the database is at the version the binary expects:

```bash
docker compose -f docker-compose.yaml exec app agentarea check-migrations
```

Expect `Database is up to date`. Check the migration run itself succeeded:

```bash
docker compose -f docker-compose.yaml logs app_migrations
```

On Kubernetes:

```bash
kubectl logs -n agentarea -l app.kubernetes.io/component=migration
kubectl get jobs -n agentarea
```

The Job should read `1/1`.

Confirm the schema is actually usable:

```bash
docker compose -f docker-compose.yaml exec db \
  psql -U "$AGENTAREA_DB_USER" -d "$AGENTAREA_DB_NAME" -c "\dt" | head -20
```

## Troubleshooting

<AccordionGroup>
  <Accordion title="The migration Job sits in `Init:0/1` and logs `Waiting for database...`">
    Its `wait-for-db` init container polls `nc -z <host> <port>` and never times
    out. The host is `global.database.host` , or the bundled PostgreSQL service
    when that is empty. Verify the host resolves from inside the namespace and
    the port is reachable.
  </Accordion>
  <Accordion title="The migration refuses an Alembic revision">
    The database was migrated by the Python platform but did not reach its last
    Alembic revision. Upgrade it with the last Python release first (its
    `agentarea-api migrate`), then run `agentarea migrate`. Do not edit
    `alembic_version` to make the error go away; it strands the schema at an
    unknown point.
  </Accordion>
  <Accordion title="`holds N relations but neither ... nor ...; refusing to migrate it`">
    The schema has tables but no record of how they got there: a database
    restored without its version tables, or one created by hand. Restore it
    together with `alembic_version` / `goose_db_version`, or migrate into an
    empty database.
  </Accordion>
  <Accordion title="A downgraded image fails against a newer schema">
    The database records a goose version the older binary does not carry. Roll
    forward to the image that contains it; the baseline cannot be reverted.
  </Accordion>
  <Accordion title="A `helm upgrade` leaves the API running an older schema">
    The migration Job is a normal resource, not a Helm hook — the chart notes
    this is deliberate, to avoid a dependency deadlock with the database. It
    therefore does not block the Deployment rollout. Check the Job completed
    before assuming the upgrade is done. See [upgrades](/self-host/upgrades) .
  </Accordion>
</AccordionGroup>

## Related

<Columns cols={2}>
  <Card title="Deploy on Kubernetes with Helm" icon="server" href="/self-host/kubernetes">
    Install the agentarea Helm chart, decide which bundled dependencies to keep
  </Card>
  <Card title="Deploy with Docker Compose" icon="server" href="/self-host/docker-compose">
    Run the full AgentArea platform on one host with docker- compose.yaml
  </Card>
  <Card title="Upgrade a deployment" icon="server" href="/self-host/upgrades">
    Move an AgentArea deployment to a new version safely
  </Card>
  <Card title="Back up and restore" icon="server" href="/self-host/backup-and-recovery">
    Identify everything AgentArea stores, back each store up
  </Card>
</Columns>
