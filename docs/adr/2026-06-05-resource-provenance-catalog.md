# ADR-003: Built-in resources live in the registry catalog, not as tenant rows with a sentinel workspace

**Date:** 2026-06-05
**Status:** Accepted
**Deciders:** Team
**Supersedes:** the interim `source` enum + `platform` workspace approach (uncommitted working-tree changes on `feat/rebac-access-explorer`)

## Context

"Built-in / official" content (default agents, catalog MCP servers, skills, provider/model specs) was marked by the magic string `workspace_id == "system"` (with `created_by = "system"`). This is DDD-invalid: it overloads the tenant-identity field to encode *provenance* and *visibility*, points at a non-existent workspace aggregate, and violates the "never fall back to a system user/workspace" rule. Three inconsistent checks (`created_by=='system'`, `workspace_id=='system'`, `is_builtin`/`is_public`) all tried to answer "is this built-in?".

An interim fix introduced a real `platform` workspace + a `source` provenance enum (`official|workspace_custom|imported`) on the four tenant tables. Review surfaced that this only **renamed the sentinel**: built-in was now marked twice (workspace=`platform` AND source=`official`), and `imported` is a weak category that discards the one useful fact — *where a copy came from* and *whether it can be updated*.

Crucially, the codebase already has the industry-standard mechanism: the `registries` / `registry_items` catalog. `registry_items` carries the full `spec`, a `version`, `installed_entity_id` (the materialized tenant copy), and `installed_version` + `update_available`. MCP servers and skills already flow through it; only `default_agents` bypasses it by writing directly into `agents`.

## Decision

**The catalog is the single home of built-in/official definitions; tenant tables hold only owned instances; provenance is a link from instance to catalog item, not a flag or a workspace value.**

This is the catalog-vs-instance split (Docker image/registry → container; AMI → EC2 instance; GitHub template → repo; Backstage template → component): a published definition is referenced and *instantiated*, never auto-copied into every tenant.

Concretely:

1. **Catalog = `registries` / `registry_items`, global (not tenant-scoped).** Synced by the operator. Built-in agents become `registry_items` of `registry_type='agents'` with the definition in `spec` — exactly how MCP/skills already work. The operator stops materializing `agents` rows.

2. **Instances stay tenant-owned and normal.** `agents` / `skills` / `mcp_server_instances` / `provider_configs` always have a real `workspace_id` + `created_by`. No `source` column, no built-in flag, no `platform` owner.

3. **Provenance + updates via the existing catalog linkage**, not an enum:
   - forward: instance points to its origin (`registry_item_id` — already on skills/MCP; add to agents).
   - reverse + version: `registry_items.installed_entity_id` + `installed_version` vs `version` → `update_available`.
   - "created from scratch" = no `registry_item_id` (null). "Installed from X" = set. This is the `orgid/item#version` reference, already modeled.

4. **Instantiation is explicit (copy-on-install / use-this-template), not auto-seeded.** A built-in becomes a tenant row only when a user adds/customizes it. This is the dominant industry pattern and reuses the bundle installer (#214) — installing one catalog item is a one-item bundle. No mass copying into every workspace.

5. **Built-in = "is a `registry_item`".** The single predicate replaces all three legacy checks. Export excludes nothing special at the instance level except instances linked to an official catalog item if/when we choose to.

6. **Visibility:** the catalog is globally readable (it is not tenant-scoped). Instances are owner-scoped as usual. No workspace string is injected into `accessible_workspaces` for built-ins. Per-resource sharing remains a separate axis (Ory Keto, deferred — see [project_mcp_visibility_rebac]).

## Options evaluated

- **A. Sentinel rename (`platform` workspace + `source` enum).** Removes the literal but keeps provenance fused with tenant identity and double-marks built-ins. Rejected (the interim approach).
- **B. `is_official` boolean + `derived_from` ref on tenant tables.** Cleaner, but still puts catalog definitions in tenant tables and needs a special owner. Half-measure.
- **C. Catalog-vs-instance split reusing `registry_items` (chosen).** No new tables, matches MCP/skills, matches industry. Built-ins are catalog items; instances reference them.

## Consequences

- **Behavioral change:** default/built-in agents no longer appear pre-materialized in every workspace; they are browsable catalog items instantiated on demand. UI renders the catalog and an "add/use" action; an "update available" affordance follows from `installed_version` vs `version`.
- `source` enum, the `platform` workspace row, `PLATFORM_*` constants, the `is_builtin(source)` predicate, and the `accessible_workspaces += platform` trick are all removed.
- `default_agents` registry handling writes catalog items, not `agents`. The registry type is renamed `default_agents → agents` to match the other types (which are named by entity).
- Agents gain `registry_item_id` (nullable) for forward provenance; skills/MCP already have it.
- Migration: existing seeded rows (currently `workspace_id` in `system`/`platform`) for agents are converted into `registry_items` (catalog) and de-materialized from `agents`; or, where an instance must be preserved, kept as a tenant instance with `registry_item_id` set. Backfill is one-way.

## What this is NOT

- Not a new per-entity `*_definitions` table — the catalog already exists (`registry_items`).
- Not Keto/ReBAC visibility — that is a separate, deferred axis.
- Not a marketplace UI — only catalog browse + instantiate.
- Not auto-seeding copies into tenants (the rejected mass-copy behavior).

## Migration order (one PR)

1. Make `registries`/`registry_items` global (drop tenant-scoping / NOT NULL `workspace_id`, or treat as globally readable); repository no longer workspace-filters the catalog.
2. Operator: `default_agents → agents` registry type; seed agent definitions as `registry_items` (`spec`), stop INSERTing `agents`. Purge remaining `'system'` literals (done in interim work) — now resolved by the catalog, not a `platform` owner.
3. Add `registry_item_id` to `agents`. Instantiation service/endpoint (reuse bundle installer) creates the tenant agent and sets `installed_entity_id`/`installed_version`.
4. Remove `source` enum + `platform` workspace + `PLATFORM_*` + `is_builtin(source)` + the `accessible_workspaces` platform injection (revert the interim changes).
5. Data migration: existing seeded agent rows → `registry_items`; de-materialize from `agents`.
6. UI: catalog browse + "add/use"; "update available" from version comparison.
7. Apply migration to a live DB and verify.
