---
title: Registry and catalog
type: concept
summary: Built-in agents, MCP servers, skills, and model specs live in a global catalog and are instantiated into a workspace on demand — not copied into every tenant behind a sentinel workspace id.
prerequisites:
  - /concepts/integration/mcp
related:
  - /concepts/integration/bundles
  - /concepts/workspaces-projects-resources
  - /concepts/agents/what-is-an-agent
last_updated: 2026-07-29
---

# Registry and catalog

A registry is a configured external source of definitions. A catalog item is one
cached definition from that source. Both are global — they are not scoped to a
workspace, and every workspace reads the same catalog. A workspace gets its own
copy of something only when a user asks for one.

## The problem

"Built-in" and "owned by this workspace" are different facts, and the obvious
implementation fuses them.

The fused version marks official content with a magic tenant id —
`workspace_id == "system"` — and it fails in several directions at once. It
overloads the tenancy field to encode provenance, and points it at a workspace
that does not exist. It makes "is this built-in?" ambiguous, because three
different checks end up answering it. And once built-ins are rows in tenant
tables, updating one upstream means migrating N copies, with no way to tell an
untouched built-in from one a user customized.

Renaming the sentinel does not fix it. An interim design used a real `platform`
workspace plus a `source` enum, which marked built-ins twice and still discarded
the fact worth keeping: where a copy came from and whether it can be updated.

## How AgentArea approaches it

### Two tables, both global

`registries` records a source: a `registry_type`, a `source_type` of `url`,
`github`, or `api`, a `source_url`, a `sync_mode` (default `manual`), plus sync
bookkeeping — `last_synced_at`, `last_sync_error`, `item_count`.

`registry_items` records one cached entry: `external_id` (the source's
identifier, and the idempotency key), `name`, `description`, `version`, `tags`,
and a `spec` JSONB carrying the full definition.

Neither carries a `workspace_id`. Repositories do not workspace-filter the
catalog.

### Six types, inferred from the document

`mcp_servers`, `skills`, `llm_providers`, `llm_models`, `agents`, `bundles`.
Each catalog document carries exactly one top-level key — `servers`, `skills`,
`providers`, `models`, `agents`, `bundles` — so the type can be inferred from
the payload when it is not stated. Two matching keys is an error, not a guess.

Sources are fetched as JSON or YAML, detected by content type and file
extension, with a JSON parse falling back to YAML.

### Catalog-only versus materialized-on-sync

This is the part where the intent and the current code differ, and the
difference matters if you are reasoning about where a row lives.

**`agents` and `bundles` are catalog-only.** Sync writes the `registry_item` and
nothing else — the entity creation step returns nothing. A built-in agent *is*
its catalog item; the `spec` holds the instruction, tools, planning flag, and
`preferred_models`. A catalog bundle's `spec` is the canonical bundle document
itself.

**The other four still materialize an entity at sync time.** `mcp_servers`
creates an `MCPServer` spec row, `skills` creates a `Skill`, `llm_providers`
upserts a `ProviderSpec`, and `llm_models` upserts a `ModelSpec`. These are
written by whatever repository context ran the sync, and `MCPServer` and `Skill`
are workspace-scoped, so a synced MCP server spec is owned by the workspace whose
context performed the sync.

### Provenance is a link, not a flag

Forward: an instance records `registry_item_id`, pointing at the catalog item it
came from. Null means "created from scratch".

Reverse and per-workspace: `registry_item_installs` maps
`(registry_item_id, workspace_id)` to `installed_entity_id` and
`installed_version`, with a uniqueness constraint on the pair. That is how a
globally-shared catalog answers a per-workspace question — "have I installed
this here, and at what version".

`CatalogAgentRepository` reads catalog agents with a `LEFT JOIN` on that table
filtered to the caller's workspace, so one query returns the definition plus
this workspace's install state. Installing calls `mark_installed`, an upsert on
the pair.

"Built-in" therefore has one predicate: it is a `registry_item`.

### Updates are flagged, never applied

Re-syncing an existing item overwrites its `name`, `description`, `spec`, and
`tags`, and sets the new `version`. If the item has an `installed_version` and
that version differs, `update_available` is set to true.

Nothing is applied automatically. Applying is an explicit call —
`POST /v1/registries/catalog/items/{item_id}/update` for one item, or
`POST /v1/registries/{registry_id}/update-all` for every flagged item in a
registry — which writes the new spec onto the installed entity and clears the
flag.

### The catalog is global, so it cannot hold workspace-local ids

A catalog agent's spec carries `preferred_models` — model slugs in priority
order — and never a concrete `model_id`. Model instances are per-workspace UUIDs;
a global definition that named one would be meaningless in every other
workspace. Resolution happens at install time.

## Why not seed a copy into every workspace

Auto-materializing built-ins into each tenant is the design this replaced.

Every upstream change becomes N row migrations. There is no way to distinguish
an untouched copy from one a user edited, so an update either clobbers local
changes or skips everyone. Deleting a built-in has to be replayed per workspace.
And a new workspace pays a seeding cost proportional to the catalog.

The reference-and-instantiate shape is what Docker images, AMIs, GitHub
templates, and Backstage templates all use, for the same reasons.

## Why not an `is_builtin` flag or a `source` enum on tenant tables

It is cleaner than a sentinel workspace and still wrong. It keeps catalog
definitions inside tenant tables, so a built-in still needs an owner; it marks
the same fact twice once you also record where a copy came from; and an enum
value like `imported` throws away the only genuinely useful part — the origin
reference and the version, which are what make "update available" answerable.

## Why not a `*_definitions` table per entity type

Adding `agent_definitions`, `skill_definitions`, `mcp_server_definitions` is a
new mechanism for something the codebase already had. `registry_items` already
carried `spec`, `version`, `installed_entity_id`, and `installed_version`, and
MCP servers and skills already flowed through it. Adding parallel tables would
have left two answers to "where does a built-in definition live".

## Limits

- **The catalog is readable by everyone.** Global-not-tenant-scoped is the
  design; there is no per-item visibility axis in this model.
- **Trusting a registry is trusting its URL.** Sync fetches over HTTP(S) with a
  120-second timeout, no signature verification, and no content pinning. A
  compromised source URL changes what every workspace sees.
- **Nothing schedules a sync.** `sync_mode` defaults to `manual` and this service
  contains no scheduler. Syncs are triggered by an explicit call to
  `POST /v1/registries/{registry_id}/sync`.
- **Version comparison is string inequality, not semver.** A version that differs
  in any direction sets `update_available`, including a downgrade.
- **The catalog-only types have no "apply update" path.** `update_item_spec`
  refuses when `installed_entity_id` is null, which is always true for `agents`
  and `bundles`. An updated catalog agent is picked up the next time it is read
  or instantiated, and a workspace that already installed it keeps its copy.
- **Provenance links can dangle.** Deleting a registry cascades its items and
  their install rows, but `registry_item_id` on an MCP server or skill is a plain
  column with no foreign key. It survives as a pointer to nothing.
- **Sync failure is partial.** Items are processed in a loop; an exception
  mid-loop records `last_sync_error` and re-raises, leaving earlier items already
  committed.
- **Slug collisions are resolved by suffix, up to 999.** A materialized entity
  whose name collides gets `-2` through `-999`; beyond that the sync fails.

## Related

- [Bundles](/concepts/integration/bundles) — the format a catalog `bundles` item
  holds.
- [MCP](/concepts/integration/mcp) — what a synced `mcp_servers` item becomes.
