# Per-operation tool governance — design

**Date:** 2026-08-11
**Branch:** feat/per-operation-tool-governance
**Status:** draft for review (brainstorming output; not yet a plan)

## Problem

Today the platform governs a code toolset as one aggregate identity. A policy
targets `tool:web` or `tool:files`, and `get_code_tools_metadata()` describes a
toolset as a single capability. That is too coarse: an operator cannot allow
`web_search` while denying `web_fetch_webpage`, nor require approval on
`files_save_file` but not `files_read_file`. Every method of a toolset shares
one grant, one deny, one approval flag.

**Goal:** govern each toolset *operation* independently — its own
allow/deny/approval policy target, its own disclosure — while keeping the
existing policy engine, the aggregate rows already in the database, and the
runtime contract unchanged.

This is genuinely net-new relative to `main` (which only has toolset-level
authz). It is the salvage-worthy core of the stale `wip/tool-authz-websearch`
branch. The web-search half of that branch is **out of scope** — superseded by
`main`'s egress-service web search/fetch (see the web decision below).

## Scope

**In:** per-operation identity for code / MCP / OpenAPI / agent tools; a
migration that splits existing aggregate policy rows into per-operation rows;
per-operation `available_methods` metadata; per-target execution dispatch;
per-operation approval in agent import/export.

**Out:** the WIP's in-worker web fetch + `SearchProvider`/SearXNG (Theme B) —
discarded; `main`'s egress `WEB_SEARCH_BASE_URL` / `WEB_FETCH_BASE_URL` stays.
OpenAPI operation-id hygiene (Theme C) already shipped in PR #332.

## Design

### 1. Per-operation identity — `ToolRef` / `ToolSurface`

A model-visible tool becomes a `ToolSurface` carrying one canonical schema, its
visible name, a bound handler, and a routing identity `ToolRef`:

```
ToolRef(source_type, source, operation, policy_name)
```

- `source_type` — `code` | `mcp` | `openapi` | `agent`
- `source` — the toolset namespace / connection / delegated-agent identity
- `operation` — the specific method (e.g. `search`, `read_file`)
- `policy_name` — stable governance target (may differ from an execution-scoped
  alias in legacy workflow histories)

A toolset instance exposes `get_tool_surfaces()`; the runtime governs and
dispatches per surface instead of per toolset.

### 2. Policy target schema

Per-operation targets use the operation's visible name: `tool:web_search`,
`tool:web_fetch_webpage`, `tool:files_read_file`, … The existing
`PolicyRule` / `PolicyDocument` model is unchanged — only the *granularity* of
`target` changes. Targets remain **not source-qualified** (the same raw name may
belong to a code op, an MCP tool, or an OpenAPI op); resolving that ambiguity is
a separate, later concern and this design must not assume source-qualified
targets.

### 3. `available_methods` metadata contract

`get_code_tools_metadata(*, unavailable_methods: Mapping[namespace, set[method]])`
returns, per toolset namespace, an `available_methods` list where each entry is:

```
{ name, tool_name (visible), display_name, description, requires_user_confirmation }
```

`unavailable_methods` lets the **control plane** hide an operation whose runtime
dependency is absent, without teaching the SDK registry about deployment
specifics. Concretely: gate `web_search` when the deployment has no web-search
egress configured. **Adapt the gate to `main`:** key it off `WEB_SEARCH_BASE_URL`
/ `WEB_FETCH_BASE_URL` (the shipped egress config), NOT the WIP's `SEARXNG_URL`.

### 4. Migration / backfill

A single Alembic revision (`…_tool_operations`, down-revision =
`20260727_0100_mcp_last_used` **must be re-pinned to the current head**):

- For every enabled aggregate rule (`tool:web`, `tool:files`, …), copy it to
  each operation that exists at this revision, from a **historical snapshot**
  baked into the migration (never import the mutable app registry).
- **Keep the aggregate row** — the same raw name may still govern an external
  MCP/OpenAPI source; the runtime just stops giving it toolset-wide semantics.
- **Idempotent:** each migrated row gets a deterministic `uuid5(namespace,
  source_rule_id + operation)` id, so re-running never duplicates, even if the
  migrated row was edited afterward. A semantically identical operation rule is
  left in place; one that differs (params/condition/enabled/priority) is treated
  as an independent decision and preserved.
- **Agent-config cleanup:** drop the removed `math` toolset and the retired
  `extract_text` method value; record operation placeholders so the editor can
  reconstitute rule-backed approval state.
- **Delegation + OpenAPI expansion:** expand aggregate agent-delegation rows via
  the historical `delegate_to_*` sanitizer; derive OpenAPI operation names from
  the stored connection spec/inventory filtered by the config's `allowed_tools`.
  If an approved OpenAPI config has **no persisted surface** to derive exact
  names, **abort the upgrade** — never silently drop governance intent or invent
  a wildcard.
- **Downgrade is blocked** (raise): collapsing operation rules would discard
  operation-specific decisions; restoring `math`/retired flags would clobber
  post-upgrade agent edits.

**Snapshot must be regenerated against current `main`**, not copied from the WIP:
the WIP snapshot is stale (context toolset was renamed to
`read_org_file`/`list_org_files` in PR #310; `math` removed; verify
`web`/`files`/`skills`/etc. method names against the live registry before
freezing the snapshot).

### 5. Execution dispatch

The activity resolves each incoming tool call to an exact `ToolExecutionTarget`
and matches it against the agent's configured surface:

- code: match by immutable namespace identity (`type == "code"` and name equals
  the target source).
- mcp: an operation is in-surface iff it appears in the agent's `allowed_tools`
  (empty allowed set = all).
- openapi: resolve the (possibly legacy) config reference to the immutable
  connection row, then compare identity.

Dispatch governs the resolved surface through the same PDP
(`decide_tool_policy`) used by disclosure and the workflow gate — one
authorization vocabulary across every path.

### 6. Import / export shape

`CodeToolSettings` gains `tool_permissions: list[ToolPermission]` where
`ToolPermission(tool_name, requires_user_confirmation: bool | None)` names one
exact operation. `requires_user_confirmation` is **transport-only**: the API
translates it into an agent-scoped approval policy rule and does not persist it
on the tool config (it is `None` at rest and reconstituted from rules on read).
A top-level aggregate `requires_user_confirmation` is accepted **only** for
legacy code toolsets (to expand them to the per-method surface) and rejected for
MCP/OpenAPI/agent types, whose config name is not an executable operation
identity. Keep the `ToolConfig` discriminated union on `type`.

## Invariants preserved
- The typed `PolicyRule`/`PolicyResolver`/`EffectivePolicy` contract is unchanged.
- Approval stays transport-only → an agent-scoped policy rule (approval is a
  policy-engine concern, never a persisted tool-config field).
- Aggregate rows are retained; the migration is additive and idempotent.
- Two tool-authz enforcement paths exist (the PDP `decide_tool_policy` AND the
  governance interceptor-pipeline gate); per-operation identity must flow through
  both, not just the PDP.

## Reconciliation deltas vs current `main` (do NOT blindly port the WIP)
- **completion_tool:** keep `main`'s `complete(result, artifacts)` (durable
  deliverables, #277). Drop the WIP's rename to `"completion"` / dropped
  `artifacts`.
- **web availability gate:** key off `WEB_SEARCH_BASE_URL`/`WEB_FETCH_BASE_URL`,
  not `SEARXNG_URL`.
- **operation snapshot:** regenerate from the live registry (context rename, math
  removal, etc.).
- **do not reintroduce** `web_search.py` / `web_policy.py` / `searxng.py` /
  in-worker fetch. If pluggable search backends are wanted later, that is a
  feature of the egress `/search` service, not the trusted worker.

## Testing (WIP tests are the reference to re-derive on `main`)
`test_tool_target_dispatch`, `test_tool_target_rollout`, `test_tool_discovery_models`,
`test_code_tool_operation_migration`, `test_code_tool_metadata_availability`,
`test_temporal_runner_tool_targets`, `test_escalation_resolution`. Add: migration
idempotency (double-run), OpenAPI-no-surface abort, downgrade-blocked, and a real
per-operation allow/deny exercised on a live agent (authz changes are "done" only
after a real agent runs against them, not on unit tests alone).

## Risks / open questions
1. **Source-unqualified targets:** `tool:web_search` could collide with an MCP or
   OpenAPI op of the same name. Acceptable now (documented), but flag if it bites.
2. **Rollout size:** touches SDK tool model + execution + API + a data migration +
   the `ToolConfig.tsx` editor. Land the SDK/model + migration first, wire
   execution dispatch, then the editor — each independently testable.
3. **Migration head drift:** re-pin `down_revision` to the current alembic head at
   implementation time.

## Next step
On approval of this design, invoke the writing-plans skill to produce the staged
implementation plan (SDK model → migration → dispatch → API/import-export → editor),
each stage independently verifiable.
