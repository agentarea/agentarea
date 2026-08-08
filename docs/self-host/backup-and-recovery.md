---
title: Back up and restore
type: guide
summary: Identify everything AgentArea stores, back each store up, and restore in the order that produces a working system.
prerequisites:
  - /self-host/requirements
related:
  - /self-host/secrets-backends
  - /self-host/database-and-migrations
  - /self-host/upgrades
  - /self-host/kubernetes
last_updated: 2026-07-29
---

# Back up and restore

AgentArea ships no backup tooling. There is no CronJob in the chart, no
`pg_dump` script in the repository, and no snapshot command. Backup is entirely
your responsibility, and a default install has none.

This guide lists what has to be captured, in what order to restore it, and the
one item whose loss cannot be recovered from — the secret encryption key.

## Prerequisites

- Administrative access to the PostgreSQL instance
- Credentials for the object store
- `kubectl` access to the namespace, or shell access to the Compose host

## Steps

### 1. Inventory what holds state

| Store | Contents | Loss means |
|---|---|---|
| PostgreSQL `agentarea` | Agents, tasks, MCP server records, audit events, encrypted secrets | Everything the product is |
| PostgreSQL `temporal` | Workflow history for in-flight and completed tasks | Running tasks cannot resume |
| PostgreSQL `kratos` | Identities and credentials | Every user must re-register |
| PostgreSQL `openfga` | Authorization tuples | All access grants; the platform fails closed |
| PostgreSQL `keto` | Authorization tuples, when `keto.enabled=true` | As above |
| Object store: documents bucket | Uploaded files | User content |
| Object store: artifacts bucket | Task artifacts, content-addressed | Task outputs |
| `SECRET_MANAGER_ENCRYPTION_KEY` | The Fernet key for `encrypted_secrets` | Every stored credential, unrecoverably |
| Kubernetes Secrets | Database and object-store credentials, the Kratos JWKS, sandbox HMAC secrets | Recoverable by regenerating, except the encryption key |

Valkey holds Redis Streams for sandbox execution requests and channel inbound
traffic. It is working state, not a system of record. `valkey.dataStorage` is
disabled by default in the chart. Losing it drops in-flight stream entries; it
does not lose committed data.

### 2. Back up the encryption key first, and separately

`SECRET_MANAGER_ENCRYPTION_KEY` decrypts the `encrypted_secrets` table. A
database backup without it restores ciphertext nobody can open, and there is no
recovery path and no re-encryption command in the platform.

Store it somewhere that is not the database backup — otherwise one compromised
artifact yields both the ciphertext and the key.

```bash
kubectl get secret -n agentarea agentarea-app-secrets \
  -o jsonpath='{.data.encryption-key}' | base64 -d
```

Capture the other generated values at the same time, from
`agentarea-app-secrets` (`auth-secret`, `api-auth-header-value`,
`sandbox-activation-secret`), `<release>-agentarea-sandbox-cleanup-auth`
(`token`), and `<release>-kratos-jwks` (`jwks_b64`).

Losing the Kratos JWKS invalidates every issued session token — recoverable, but
every user is logged out. Losing the sandbox HMAC secrets is harmless as long as
you regenerate both sides together.

### 3. Back up PostgreSQL

Back up all databases on the instance, not just `agentarea`. A restore that
brings back the platform database while leaving `openfga` behind produces a
system where every authorization check fails closed.

```bash
pg_dumpall -h "$POSTGRES_HOST" -U "$POSTGRES_USER" \
  | gzip > agentarea-$(date +%Y%m%d_%H%M%S).sql.gz
```

Or per-database, if you prefer restoring them independently:

```bash
for db in agentarea temporal kratos openfga; do
  pg_dump -h "$POSTGRES_HOST" -U "$POSTGRES_USER" -Fc "$db" \
    > "${db}-$(date +%Y%m%d).dump"
done
```

On a managed instance, use the provider's automated backups and
point-in-time recovery instead. That is the main practical argument for setting
`postgresql.enabled=false` — the bundled StatefulSet has no replication, no
backup, and no PITR, which is why the chart's own values file marks it as not
for production.

Under Compose the database is a bind mount at `./data/postgres`. A filesystem
copy of a running PostgreSQL data directory is not a valid backup; stop the
container first, or use `pg_dump` against the running instance.

### 4. Back up the object store

The artifacts bucket is content-addressed, so objects are immutable once
written — an incremental sync is sufficient and never needs to re-transfer.

```bash
rclone sync rustfs:agentarea-documents s3-backup:agentarea-documents
rclone sync rustfs:artifacts           s3-backup:artifacts
```

Bucket names come from `global.storage.bucket` and, under Compose, from
`DOCUMENTS_BUCKET` and `ARTIFACTS_BUCKET` in `.env`. The Compose stack already
uses `rclone` for bucket creation, so the image and configuration pattern are
present in `docker-compose.yaml` to copy from.

Artifacts are referenced by checksum from rows in the `agentarea` database. Back
up the database and the artifacts bucket close together in time, or a restore
yields task records pointing at objects that are not there.

### 5. Restore

Order matters.

1. **Provision infrastructure.** Empty PostgreSQL and object store, reachable at the same names.
2. **Restore the Secrets first**, with the original encryption key. Create them before installing so the chart's `lookup` finds them and does not generate replacements.
   ```bash
   kubectl create secret generic agentarea-app-secrets -n agentarea \
     --from-literal=encryption-key='<original key>' \
     --from-literal=auth-secret='<original>' \
     --from-literal=api-auth-header-value='<original>' \
     --from-literal=sandbox-activation-secret='<original>'
   ```
3. **Restore PostgreSQL**, all databases.
   ```bash
   gunzip -c agentarea-20260729_020000.sql.gz | psql -h "$POSTGRES_HOST" -U "$POSTGRES_USER"
   ```
4. **Restore the object store.**
   ```bash
   rclone sync s3-backup:agentarea-documents rustfs:agentarea-documents
   rclone sync s3-backup:artifacts           rustfs:artifacts
   ```
5. **Install or start the platform.** The migration step runs `agentarea-api migrate`, which finds an existing revision and applies only what is outstanding — correct behaviour when restoring a backup taken from an older version. See [database and migrations](/self-host/database-and-migrations).
6. **Restore Kratos**, if it was not part of the dump. Identities live in the `kratos` database.

Restoring the database before the Secrets is the mistake that costs you the
data: the chart generates a fresh encryption key on install, and the restored
ciphertext then cannot be read with it.

### 6. Understand what a restore does not bring back

- **In-flight tasks.** Temporal workflow history restores, but the worker reconnects to a cluster whose view of time has jumped. Treat tasks that were running at backup time as lost and re-run them.
- **Sandbox state.** Sandboxes are ephemeral; nothing about a live sandbox survives.
- **Valkey stream entries** not yet consumed at backup time.

## Verify

A backup you have not restored is a hypothesis. Restore into a scratch namespace
and check all four layers.

Confirm the schema is at a known revision:

```bash
kubectl exec -n agentarea-restore deploy/agentarea-backend -- \
  sh -c 'cd /app/apps/api && alembic current'
```

Confirm the encryption key matches the restored ciphertext — this is the check
that catches the failure mode that matters:

```bash
kubectl exec -n agentarea-restore deploy/agentarea-backend -- \
  python -c "
from cryptography.fernet import Fernet
import os
Fernet(os.environ['SECRET_MANAGER_ENCRYPTION_KEY'])
print('key is well-formed')
"
```

Then read a secret back through the application — open a configured LLM provider
in the UI. If the key is wrong, the read fails with `InvalidToken`, and a
well-formed key proves nothing on its own.

Confirm row counts against the source:

```bash
psql -h "$POSTGRES_HOST" -U "$POSTGRES_USER" -d agentarea \
  -c "SELECT 'agents', count(*) FROM agents
      UNION ALL SELECT 'tasks', count(*) FROM tasks
      UNION ALL SELECT 'secrets', count(*) FROM encrypted_secrets;"
```

Confirm artifacts resolve: open a completed task in the UI and download its
artifact. That exercises the database reference, the object store, and the
presigned URL path together.

## Troubleshooting

**Everything restores, and every stored credential fails with `InvalidToken`.**
The encryption key does not match the ciphertext. Restore the original key.
There is no way to recover the plaintext without it; the secrets have to be
re-entered by hand.

**The API starts but every authorization check denies.** The `openfga` database
was not restored, or OpenFGA bootstrapped a new store. The authorization reader
fails closed, which presents as a working platform where nothing is permitted.

**Users cannot log in after a restore.** The `kratos` database or the JWKS
secret is missing. A regenerated JWKS invalidates all existing sessions; users
must sign in again.

**`helm install` against a restored database generates new credentials that do
not match it.** The chart generates secrets only when `lookup` finds none.
Create the Secrets before installing.

**Task rows exist but artifacts 404.** The database backup is newer than the
object-store copy. Restore the object store from a point at or after the
database backup, and re-run affected tasks.

**A filesystem copy of `./data/postgres` will not start.** A hot copy of a
running data directory is not consistent. Use `pg_dump`, or stop the container
before copying.

## Related

- [Choose a secrets backend](/self-host/secrets-backends)
- [Run database migrations](/self-host/database-and-migrations)
- [Upgrade a deployment](/self-host/upgrades)
- [Deploy on Kubernetes with Helm](/self-host/kubernetes)
