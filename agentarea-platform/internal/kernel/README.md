# kernel

Layer 1: ports and value types, no domain. Imports no module, profile, `app`
or `ext` (lint list `kernel`). Adapters live in `internal/profiles/cluster`.

| Package | What | State |
|---|---|---|
| `config` | typed env loading, fail on missing, duration/bool parsing as Python reads them, `Common` | implemented |
| `scope` | `Workspace`, workspace errors (404 not 403), workspace and entity slugs | implemented |
| `lifecycle` | ordered start, reverse stop with deadlines, background loops that fail the group | implemented |
| `money` | `Decimal` (Python `str(Decimal)` bytes), currency, billing ports | implemented (ports: adapter in enterprise) |
| `obs` | log keys, telemetry, redaction | adapter: to implement |
| `httpx` | problem+json, 422 shape, pagination, router, middleware | adapter: to implement |
| `authn` | principal, caller, credentials, verifiers, turn tokens | adapter: to implement |
| `authz` | OpenFGA graph: check, list objects, write; workspace authority | adapter: to implement |
| `db` | `Querier` (sqlc DBTX), workspace `Session`, read/write pools, advisory lock, `Config` | adapter: to implement |
| `events` | envelope, publisher/subscriber/stream, outbox, broker, dedup | adapter: to implement |
| `durable` | workflow executor, worker, activity kinds | adapter: to implement |
| `secrets` | manager, Fernet cipher, references | adapter: to implement |
| `blob` | object store | adapter: to implement |
| `netguard` | outbound address policy, pinned dialer, trust | adapter: to implement |
| `mcpserve` | platform MCP mounts and toolsets | adapter: to implement |
