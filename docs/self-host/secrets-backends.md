---
title: Choose a secrets backend
type: guide
summary: Configure where AgentArea stores workspace secrets — encrypted in PostgreSQL or in Infisical — and supply the deployment secrets the chart would otherwise generate.
prerequisites:
  - /self-host/requirements
related:
  - /self-host/configuration
  - /self-host/kubernetes
  - /self-host/docker-compose
  - /self-host/backup-and-recovery
last_updated: 2026-07-29
---

# Choose a secrets backend

AgentArea handles two different kinds of secret, and they are stored in
different places by different mechanisms. Confusing them is the usual reason a
deployment ends up with credentials somewhere the operator did not expect.

| Kind | Examples | Stored by | Configured by |
|---|---|---|---|
| Deployment secrets | database password, object-store keys, the sandbox HMAC secrets, the Kratos JWKS | Kubernetes Secrets, or `.env` under Compose | `global.secrets.*`, or the environment file |
| Workspace secrets | LLM provider API keys, MCP server credentials, OAuth tokens | The secret manager backend | `SECRET_MANAGER_TYPE` |

This guide covers both. The secret manager backend is the choice with
consequences; the deployment secrets are mostly about supplying your own instead
of letting the chart generate them.

## Prerequisites

- A running or planned deployment — see [Kubernetes](/self-host/kubernetes) or [Docker Compose](/self-host/docker-compose)
- For Infisical: a project, a machine identity, and its client ID and client secret

## Steps

### 1. Choose a workspace secret backend

Two backends exist. `SECRET_MANAGER_TYPE` selects between them, and any other
value raises `Invalid SECRET_MANAGER_TYPE` at startup rather than falling back.

**`database` (default).** Secrets are encrypted with Fernet and stored in the
`encrypted_secrets` table in the platform's own PostgreSQL database, scoped by
`workspace_id`. Pick this when you do not already run a secret manager: it adds
no operational surface, and the ciphertext is covered by your existing database
backup. The tradeoff is that the encryption key travels as an environment
variable next to the database that holds the ciphertext, so anyone who can read
both the pod environment and the database can read every stored credential.

**`infisical`.** Secrets are read from and written to an Infisical instance
through the `infisical-sdk` client. Pick this when you already operate
Infisical and want credential storage outside the application database.

### 2. Configure the `database` backend

Generate a Fernet key. It must be a real Fernet key, not an arbitrary string.

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

On Kubernetes the chart generates this for you into the
`agentarea-app-secrets` Secret under key `encryption-key`, and reuses the
existing value on every subsequent upgrade. To supply your own, create the
Secret before installing:

```bash
kubectl create secret generic agentarea-app-secrets \
  --namespace agentarea \
  --from-literal=encryption-key="$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')" \
  --from-literal=auth-secret="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')" \
  --from-literal=api-auth-header-value="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')" \
  --from-literal=sandbox-activation-secret="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
```

All four keys must be present. The chart reads each by name, and a Secret
missing `encryption-key` leaves the API crash-looping at startup.

Under Compose, set it in `.env`:

```bash
SECRET_MANAGER_TYPE=database
SECRET_MANAGER_ENCRYPTION_KEY=<the generated key>
```

This key cannot be rotated in place. Changing it makes every secret already
written unreadable — `Fernet` raises `InvalidToken` on decrypt, and there is no
re-encryption path in the platform. Treat it as permanent for the life of the
database, and back it up separately from the database itself, or a restore gives
you ciphertext you cannot open.

### 3. Configure the `infisical` backend

```yaml
backend:
  extraEnv:
    - name: SECRET_MANAGER_TYPE
      value: infisical
    - name: SECRET_MANAGER_ENDPOINT
      value: https://infisical.example.com
    - name: SECRET_MANAGER_ACCESS_KEY
      valueFrom:
        secretKeyRef: { name: agentarea-infisical, key: client-id }
    - name: SECRET_MANAGER_SECRET_KEY
      valueFrom:
        secretKeyRef: { name: agentarea-infisical, key: client-secret }

worker:
  extraEnv:
    # the same four variables
```

Set the same variables on the worker. The worker resolves secrets when it runs
agent activities, so a backend configured on the API alone leaves task execution
unable to read provider credentials.

`SECRET_MANAGER_ENDPOINT` defaults to `https://app.infisical.com` when unset.
Both `SECRET_MANAGER_ACCESS_KEY` and `SECRET_MANAGER_SECRET_KEY` are required;
the factory raises `Infisical credentials not configured` at startup if either
is missing, before any request is served.

The `infisical-sdk` package must be installed in the image. If it is not, the
factory raises `Infisical SDK not installed`.

### 4. Supply the deployment secrets

On Kubernetes the chart generates any of these that do not already exist, and
annotates each with `helm.sh/resource-policy: keep` so `helm uninstall` leaves
them behind. On upgrade it looks each one up and reuses the existing value, so
credentials do not rotate underneath a running deployment.

| Secret name (default) | Keys | Created when |
|---|---|---|
| `agentarea-postgresql-secret` | `username`, `password`, `postgres-password` | `postgresql.enabled=true` |
| `agentarea-redis-secret` | `redis-password` | `redis.enabled=true` |
| `agentarea-rustfs-secret` | `root-user`, `root-password` | `rustfs.enabled=true` |
| `agentarea-app-secrets` | `auth-secret`, `encryption-key`, `api-auth-header-value`, `sandbox-activation-secret` | always |
| `<release>-agentarea-sandbox-cleanup-auth` | `token` | always |
| `<release>-kratos-jwks` | `jwks_b64` | `kratos.enabled=true` and `kratos.generateJwks=true` |

Rename any of them through `global.secrets.postgresql`, `global.secrets.redis`,
`global.secrets.rustfs`, and `global.secrets.application` to point at Secrets you
manage yourself — with an external secrets operator, for instance.

When you disable a bundled dependency, the chart stops generating its Secret.
Setting `postgresql.enabled=false` means you must create
`agentarea-postgresql-secret` with `username` and `password` yourself, because
the migration Jobs and every service still read it.

### 5. Replace the development credentials under Compose

`.env.example` ships values that are fine to develop against and not fine to
deploy:

- `SECRET_MANAGER_ENCRYPTION_KEY` — a real Fernet key, committed to the repository
- `SANDBOX_ACTIVATION_AUTH_SECRET` and `SANDBOX_CLEANUP_AUTH_SECRET` — placeholders that say `change-in-prod`; both must be at least 32 bytes
- `KRATOS_JWKS_B64` — a test JWKS **including the private key `d`**, so anyone with the repository can mint tokens the API will accept
- `POSTGRES_PASSWORD=postgres`, `RUSTFS_ACCESS_KEY=minioadmin`, `RUSTFS_SECRET_KEY=minioadmin`

Compose declares the two sandbox secrets with `${VAR:?...}`, so an empty value
aborts the run instead of starting an unauthenticated sandbox activation path.
The others have working defaults and will not stop you.

## Verify

Confirm the backend the API actually selected. `SecretManagerFactory` logs its
type on initialization:

```bash
kubectl logs -n agentarea -l app.kubernetes.io/component=backend | grep SecretManagerFactory
```

```
Initialized SecretManagerFactory with type: database
```

Under Compose:

```bash
docker compose -f docker-compose.yaml logs app | grep SecretManagerFactory
```

Then confirm a round trip through the real path: add an LLM provider key in the
UI under the provider configuration, and check that a row appears without the
plaintext being visible.

```bash
docker compose -f docker-compose.yaml exec db \
  psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -c "SELECT workspace_id, secret_name, left(encrypted_value, 12) FROM encrypted_secrets;"
```

The `encrypted_value` prefix should be Fernet ciphertext (`gAAAAA...`), not the
key you typed. If you configured Infisical, the table stays empty and the secret
appears in your Infisical project instead.

## Troubleshooting

**API exits at startup with `SECRET_MANAGER_ENCRYPTION_KEY environment variable
must be set`.** The `database` backend has no key. This is validated in
`SecretManagerFactory.__init__`, so it fails at construction rather than on the
first secret read — the process will not serve traffic in a state where secret
storage is broken.

**Reads fail with `InvalidToken` after a restore or a redeploy.** The encryption
key no longer matches the ciphertext. Restore the original key. There is no
recovery path from the database side, and no re-encryption command; if the key
is genuinely lost, every stored credential has to be re-entered.

**Agents fail on tool calls with a missing credential, but the UI shows the
secret saved.** The worker and the API disagree on `SECRET_MANAGER_TYPE` or on
the key. Both processes construct their own secret manager. Compare the
`Initialized SecretManagerFactory with type:` line in each.

**`helm upgrade` rotates a password and breaks the database connection.** This
happens when the Secret was deleted between operations — the chart's `lookup`
finds nothing and generates a fresh value, while the PostgreSQL volume still has
the old one. The `helm.sh/resource-policy: keep` annotation prevents this on
uninstall, but not against a manual `kubectl delete secret`.

**Infisical is configured but startup raises `Infisical SDK not installed`.**
The `infisical-sdk` package is absent from the image. It is an optional
dependency of the platform.

## Related

- [Configuration](/self-host/configuration)
- [Deploy on Kubernetes with Helm](/self-host/kubernetes)
- [Back up and restore](/self-host/backup-and-recovery)
- [Troubleshoot a self-hosted deployment](/self-host/troubleshooting)
