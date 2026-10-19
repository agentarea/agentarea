---
title: Upgrade a deployment
type: guide
description: "Move an AgentArea deployment to a new version safely, including which image tag to pin and how to confirm migrations applied."
prerequisites:
  - /self-host/backup-and-recovery
related:
  - /self-host/env-migration
  - /self-host/database-and-migrations
  - /self-host/kubernetes
  - /self-host/docker-compose
  - /self-host/troubleshooting
last_updated: 2026-10-15
---

An AgentArea upgrade is a schema migration plus a set of image replacements. The
schema migration is the part that can go wrong in a way you cannot undo, so the
sequence is: back up, pin a version, upgrade, confirm the migration Job
succeeded, not merely that the pods restarted.

The chart's migration Job is a normal resource, not a Helm hook. The chart notes
this is deliberate, to avoid a dependency deadlock with the database. The
consequence is that it does not gate the Deployment rollout: `helm upgrade
--wait` can return success while the migration is still running or has failed.
Check the Job explicitly.

## Prerequisites

<Info>
- A verified backup — see [back up and restore](/self-host/backup-and-recovery)
- The version you are upgrading to, and the one you are on
- For Kubernetes: `helm` and `kubectl` against the target namespace
</Info>

## Steps

<Steps titleSize="h3">
  <Step title="Choose a tag to pin">
    Images are published to Docker Hub as
    `agentarea/agentarea-<component>` for components `agentarea-api`,
    `agentarea-worker`, `agentarea-frontend`, `agentarea-mcp-manager`,
    `agentarea-events`, and `agentarea-mcp-runner`.

    | Tag | Mutable | Produced by |
    |---|---|---|
    | `X.Y.Z-<short-sha>` | no | CI on merge to `main`; the 7-character SHA is fixed-length by design |
    | `X.Y.Z` | no | the release workflow, on push of a `vX.Y.Z` tag |
    | `X.Y` and `X` | yes | the release workflow, moved to the newest matching release |
    | `latest` | yes | the release workflow, moved on every release |

    The release workflow does not rebuild. It retags the existing
    `X.Y.Z-<short-sha>` artifact that CI already pushed, so the bytes you test on a
    release tag are the bytes CI built from `main`.

    Pin `X.Y.Z` for any deployment you care about. `latest` moves under you on
    someone else's schedule, and a merge to `main` alone does not move it — only a
    tag push does, which makes `latest` both mutable and unpredictable in timing.

    The chart's `values.yaml` defaults every image tag to `latest`. Override them:

    ```yaml
    global:
      version: "0.0.13"
    backend:
      image: { tag: "0.0.13" }
    worker:
      image: { tag: "0.0.13" }
    frontend:
      image: { tag: "0.0.13" }
    mcpManager:
      image: { tag: "0.0.13" }
    eventService:
      image: { tag: "0.0.13" }
    ```

    Chart version and application version are separate: `Chart.yaml` carries
    `version` (the chart) and `appVersion` (the platform). The release workflow bumps
    `Chart.yaml` and opens a pull request; do not bump chart versions by hand.
  </Step>

  <Step title="Back up before touching anything">
    Migrations are not reversible in practice. Alembic can generate a `downgrade`,
    but nothing in this repository tests one, and a downgrade that drops a column
    destroys the data in it.

    Capture the database, the object store, and the encryption key. See
    [back up and restore](/self-host/backup-and-recovery).
  </Step>

  <Step title="Read what changed">
    Every environment variable AgentArea reads was renamed to the
    `AGENTAREA_<DOMAIN>_<KEY>` scheme. Old names are ignored rather than
    honoured, so translate `.env` and your Helm values before upgrading:
    [Environment variable migration](/self-host/env-migration).

    Check the GitHub release notes for the target version. Look specifically for
    new required configuration — a variable added to `charts/agentarea/config.yaml`
    between your version and the target becomes a hard startup failure if the
    platform validates it, which is the intended behaviour rather than a silent
    default.

    Diff the chart values if you are jumping more than a patch release:

    ```bash
    helm show values agentarea/agentarea --version <new> > /tmp/new-values.yaml
    helm get values agentarea -n agentarea > /tmp/current-values.yaml
    diff /tmp/current-values.yaml /tmp/new-values.yaml
    ```
  </Step>

  <Step title="Existing cluster: move Valkey onto a volume">
    Charts released before Valkey became a store ran it on an `emptyDir` with a
    256 MiB limit and no AOF. The first upgrade to a chart with
    `valkey.dataStorage.enabled: true` creates a PVC and recreates the Valkey pod
    on it, with `appendonly yes`, `appendfsync everysec`, and
    `maxmemory-policy noeviction`.

    Everything Valkey held in memory is lost at that moment. Today that is
    transient state only: live task-event tails, sandbox execution requests,
    channel inbound streams, and caches. Task events that matter are already in
    PostgreSQL. Stream events run on Valkey from the release that moves the event
    bus there (next step), so move Valkey onto a volume in an earlier upgrade, when
    the loss is still a few unconsumed stream entries rather than undelivered
    stream events.

    Choose the StorageClass and size before you upgrade. An empty `className`
    uses the cluster's default StorageClass; a node-local class such as
    `local-path` pins Valkey to the node that holds its volume.

    ```yaml
    valkey:
      dataStorage:
        className: ""          # or the StorageClass name to use
        requestedSize: "4Gi"
    ```

    See the Valkey step in [Deploy on Kubernetes](/self-host/kubernetes) for how
    to size memory. After the upgrade, confirm AOF is on. The Deployment is
    named `<release>-valkey`:

    ```bash
    REDIS_PASSWORD=$(kubectl get secret -n agentarea agentarea-redis-secret \
      -o jsonpath='{.data.redis-password}' | base64 -d)
    kubectl exec -n agentarea deploy/agentarea-valkey -- \
      valkey-cli -a "$REDIS_PASSWORD" --no-auth-warning CONFIG GET appendonly
    ```

    The reply is `appendonly` then `yes`. `CONFIG GET maxmemory-policy` returns
    `noeviction`, and `kubectl get pvc -n agentarea` lists the Valkey claim as
    `Bound`.
  </Step>

  <Step title="Existing cluster: stream events move onto Valkey">
    Before this release, stream events were journaled in PostgreSQL and a worker
    loop dispatched them to subscriptions. From it, intake publishes each event to
    `<namespace>.streams.events.<partition>` in Valkey, and two worker consumer
    groups, `router` and `events-view`, react to it and record it. The migration
    drops the old per-subscription cursors, so an event received before the
    upgrade and not yet dispatched is not reacted to after it. Upgrade when no
    webhook or poller is sending, or accept that the last few seconds of events
    get no reaction.

    Every broker key now sits under one namespace, `AGENTAREA_EVENT_NAMESPACE`
    (default `agentarea`), which replaces `AGENTAREA_KAFKA_PREFIX`:

    | Before | After |
    |---|---|
    | `events:task.<id>` | `agentarea.tasks.events.<id>` |
    | `events:<event type>` | `agentarea.domain.events.<event type>` |
    | `agentarea.channel.inbound`, `agentarea.channel.outbound` | unchanged |

    If you set `AGENTAREA_CHANNEL_IN_STREAM` or `AGENTAREA_CHANNEL_OUT_STREAM` with
    an `agentarea.` prefix, drop the prefix: the namespace adds it. An open task
    page loses its live tail at the switch and picks it up again on reload.

    The API, worker, `agentarea-events` and `agentarea-mcp-manager` all publish
    under the namespace. Roll them to the same release together; while versions
    are mixed, old and new components write to different keys.

    `AGENTAREA_EVENT_PARTITIONS` (default 16) maps each stream to one partition.
    Choose it before the first start. Changing it later moves streams to other
    partitions, so stop intake and let the `router` group drain first.
  </Step>

  <Step title="Existing cluster: task events move to one topic and a delivery group">
    From this release a run publishes each event of its task once, to
    `<namespace>.tasks.events`, after the task log stores it. Replies to chats,
    mail, task webhooks and A2A push configs are sent by the `delivery` consumer
    group on that topic, which reads each task's reply targets. Live-only signals
    (a call started, reply chunks, tool progress) go over pub/sub
    `<namespace>.tasks.live.<task id>` and are never kept.

    | Before | After |
    |---|---|
    | `agentarea.tasks.events.<task id>` (one stream per task) | `agentarea.tasks.events` (one stream; the task id is each entry's subject) |
    | `agentarea.channel.outbound`, `agentarea.channel.outbound.dlq` | removed; group `delivery` on `agentarea.tasks.events`, dead letters in `agentarea.tasks.events.delivery.dlq` |

    Before you upgrade, let `agentarea.channel.outbound` drain: a reply still on it
    is not sent after the upgrade. Check its pending count is 0
    (`XPENDING agentarea.channel.outbound delivery`), then delete it and the
    per-task streams:

    ```bash
    valkey-cli -a "$REDIS_PASSWORD" --no-auth-warning DEL agentarea.channel.outbound agentarea.channel.outbound.dlq
    valkey-cli -a "$REDIS_PASSWORD" --no-auth-warning --scan --pattern 'agentarea.tasks.events.*' \
      | grep -v '\.delivery\.dlq$' | xargs -r valkey-cli -a "$REDIS_PASSWORD" --no-auth-warning DEL
    ```

    Remove `AGENTAREA_CHANNEL_OUT_STREAM`, `AGENTAREA_CHANNEL_OUT_GROUP` and
    `AGENTAREA_CHANNEL_OUT_DLQ` if you set them; nothing reads them.

    The task page, A2A and the CLI read a task's history from its log and resume
    by its position (`seq`). An open task page loses its live tail at the switch
    and picks it up again on reload. Every topic is now trimmed by age as it is
    written: `streams.events` by `AGENTAREA_EVENT_RETENTION`, `tasks.events` and
    `channel.inbound` after 72 hours, dead-letter topics after 14 days.
  </Step>

  <Step title="Upgrade on Kubernetes">
    ```bash
    helm repo update
    helm upgrade agentarea agentarea/agentarea \
      --namespace agentarea \
      -f values.yaml \
      --wait --timeout 15m
    ```

    The upgrade re-runs the database-creation Jobs (idempotent), the `db-migration`
    Job, and the `registry-reconcile` Job, then rolls the Deployments.

    Generated secrets are preserved. The chart looks each one up and reuses the
    existing value, so the database password and the encryption key do not rotate
    under a running deployment.

    `--wait` waits on the Deployments. It does not wait on the migration Job in a
    way you should trust — verify it separately, in step 7.
  </Step>

  <Step title="Upgrade on Docker Compose">
    ```bash
    cd /path/to/agentarea
    git pull                      # the Compose file bind-mounts config from the repo
    VERSION=0.0.13 docker compose -f docker-compose.yaml pull
    VERSION=0.0.13 docker compose -f docker-compose.yaml up -d
    ```

    Set `VERSION` in `.env` instead of on the command line to keep it consistent
    across invocations — every image reference in `docker-compose.yaml` is
    `${VERSION:-latest}`.

    Pull the repository as well as the images. The Compose file bind-mounts
    `./config/auth/kratos` and `./agentarea-platform/temporal-config`, so image and
    configuration have to move together.

    `app_migrations` re-runs automatically, and `app` waits for it to complete
    successfully before starting.
  </Step>

  <Step title="Confirm the migration, not only the rollout">
    This is the step that distinguishes a completed upgrade from a running one.

    ```bash
    kubectl get jobs -n agentarea
    kubectl logs -n agentarea -l app.kubernetes.io/component=migration
    ```

    The Job must read `1/1`, and the log must end in `Migrations completed
    successfully`. `ttlSecondsAfterFinished: 300` removes the Job five minutes after
    success, so a missing Job with healthy pods is fine; a Job at `0/1` is not.
  </Step>

  <Step title="Roll back if it failed">
    Rolling back images is straightforward. Rolling back the schema is not.

    ```bash
    helm rollback agentarea -n agentarea
    ```

    This reverts the chart, including image tags. It does **not** revert the
    database — the new schema stays. If the new schema is backward-compatible with
    the old code, the rollback works. If it is not, restore the database backup you
    took in step 2, and accept the loss of everything written since.

    Under Compose, set `VERSION` back and `up -d` again, with the same caveat.
  </Step>
</Steps>

## Verify

Confirm the running images are the ones you pinned:

```bash
kubectl get pods -n agentarea \
  -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.spec.containers[*].image}{"\n"}{end}'
```

```bash
docker compose -f docker-compose.yaml images
```

Confirm the schema is at the head the new code expects — these must match:

```bash
kubectl exec -n agentarea deploy/agentarea-backend -- \
  sh -c 'cd /app/apps/api && alembic current && alembic heads'
```

Confirm the API answers and reports the expected version:

```bash
curl -s http://localhost:8000/health | jq .
```

Then run one real task end to end. A platform where the API is healthy and task
execution is broken is the common post-upgrade failure, because the worker is a
separate deployment with its own image tag — and an upgrade that misses the
worker leaves old workflow code running against a new schema.

```bash
kubectl get pods -n agentarea -l app.kubernetes.io/component=worker
```

## Troubleshooting

<AccordionGroup>
  <Accordion title="`helm upgrade` reports success and the platform behaves like the old version">
    The Deployments rolled but the migration Job failed, or a component's image
    tag was not updated. Check every tag in `values.yaml` — `backend` , `worker`
    , `frontend` , `mcpManager` , and `eventService` are set independently, and
    moving four of the five is a common slip.
  </Accordion>
  <Accordion title="The migration Job fails with `relation already exists`">
    A partially applied migration from an interrupted upgrade. See
    [database and migrations](/self-host/database-and-migrations) for the stamp
    procedure, and take a backup before stamping.
  </Accordion>
  <Accordion title="The API crash-loops after upgrade on a missing environment variable">
    The new version requires configuration the old one did not. The platform
    fails loudly rather than defaulting. Add the value; do not work around it by
    reverting only the API.
  </Accordion>
  <Accordion title="Tasks fail after upgrade with workflow errors, while the API is fine">
    The worker is running an older image against a newer schema, or Temporal is
    replaying history with changed workflow code. Confirm the worker image
    matches, and read the failing workflow's history with
    `temporal workflow describe`.
  </Accordion>
  <Accordion title="`helm upgrade` rotated the database password">
    The Secret was deleted between operations, so `lookup` found nothing and
    generated a new value while the volume kept the old one. Restore the Secret
    from backup. The `helm.sh/resource-policy: keep` annotation protects against
    `helm uninstall` , not against `kubectl delete secret` .
  </Accordion>
  <Accordion title="Compose comes up with the old images">
    `VERSION` was not exported to the `pull` , or the pull was skipped. Every
    image is `${VERSION:-latest}` ; without it you get `latest` .
  </Accordion>
</AccordionGroup>

## Related

<Columns cols={2}>
  <Card title="Back up and restore" icon="server" href="/self-host/backup-and-recovery">
    Identify everything AgentArea stores, back each store up
  </Card>
  <Card title="Run database migrations" icon="server" href="/self-host/database-and-migrations">
    Apply, inspect, and recover Alembic migrations for the AgentArea schema, on
    Kubernetes and on
  </Card>
  <Card title="Deploy on Kubernetes with Helm" icon="server" href="/self-host/kubernetes">
    Install the agentarea Helm chart, decide which bundled dependencies to keep
  </Card>
  <Card title="Troubleshoot a self-hosted deployment" icon="server" href="/self-host/troubleshooting">
    Diagnose a deployment that will not start
  </Card>
</Columns>
