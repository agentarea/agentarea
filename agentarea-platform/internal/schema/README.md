# schema

Two goose sets: core embedded here, enterprise in the enterprise module.

| Set | Files | goose table | Continues Alembic | Head |
|---|---|---|---|---|
| core | `migrations/` | `public.goose_db_version` | `public.alembic_version` | `20261111_1200_source_senders` |
| enterprise | `agentarea-enterprise/platform/migrations/` (registered with `ext.WithMigrations`, built by `schema.Extension`) | `agentarea_enterprise.goose_db_version` | `agentarea_enterprise.alembic_version_enterprise` | `20261022_1200_ledger_monitor` |

`00001_baseline.sql` of each set is the schema at that head plus the rows a
fresh `alembic upgrade head` inserts: the `platform` workspace, its five
policies, the four built-in registries (Built-in MCP Servers inactive), and
the Alembic version row. The Alembic version tables are part of the baseline,
so Python still sees a Go-built database at its head. Ids and `created_at` /
`updated_at` of those rows are `gen_random_uuid()` / `now()`, as in the
migrations. Down refuses: a baseline is not reversible.

`schema.Migrate(ctx, db, schema.Core())`, then each extension set (`agentarea migrate` does both):

- Alembic table at the head: the baseline is recorded as applied, not run;
- Alembic table at any other revision: refused, the error names the revision;
- schema holds no relation: the baseline runs;
- relations but no version table: refused.

It holds an advisory lock per set while it runs.

## How the baseline is made

`pg_dump --schema-only --no-owner --no-privileges` of the database Alembic
builds (core, then the enterprise stream), split by schema, in pg_dump's order.
Changed from the dump:

- dated partitions (`stream_events_pYYYYMMDD`, `resource_usage_events_YYYY_MM`)
  are not in the file; a DO block makes them relative to `now()` the way the
  migrations do (days -1..14; this month through 12 ahead, each guarded with
  its no-truncate trigger). The default ledger partition is static;
- `(col)::text = ANY ((ARRAY['a'::character varying, ...])::text[])` is
  written `col = ANY (ARRAY[...])`: the dumped text parses to a different
  CHECK expression, this form parses to the one the migrations made;
- `SET` becomes `SET LOCAL` and `CREATE SCHEMA agentarea_enterprise` is left
  to `Migrate`, which creates it before goose puts its table there.

## Frozen baselines

The baselines were generated and checked against Alembic by
`tools/schemacheck/schemacheck.sh` while the Python backend lived in this
repository. With it gone they are frozen: a schema change is a new goose file
after the baseline, never an edit to `00001_baseline.sql`. `go run
./tools/schemacheck apply` still migrates a database through `schema.Migrate`
(the behaviour-suite stack uses it).

## Orphan tables carried

`compound_mcps` and `compound_mcp_members` (no model, no code; kept until the
port is done). Also carried with no SQLAlchemy model: `mcp_runtime_instances`,
`mcp_runtime_request_leases` (owned by the Go MCP manager) and
`graph_migrations` (raw SQL in Python).
