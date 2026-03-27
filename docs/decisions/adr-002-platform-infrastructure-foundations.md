# ADR-002: Platform Infrastructure Foundations

**Date:** 2026-03-19
**Status:** Accepted
**Branch:** jamakase/infra-fix

## Context

The governance primitives gap analysis (docs/plans/2026-03-13-governance-primitives-analysis.md)
identified a large surface of capabilities to implement. Before any of that can happen, the
platform needed a set of cross-cutting foundations that most governance features depend on:
authorization enforcement, extensible deployment modes, flexible execution engines, and
context management. This branch delivered that foundation layer.

## What Was Built

### 1. Authorization layer

**Problem:** `UserContext` carried a `roles` field that was never enforced. Any authenticated
user could call any mutating API endpoint.

**Decision:** Added a `PermissionService` interface with an OSS implementation covering
`READER` / `WRITER` / `ADMIN` roles. Mutating endpoints (`POST`, `PATCH`, `DELETE`) check
write permission before proceeding. A `simple_authorization.py` module provides the
enforcement logic; `authorization.py` defines the interface.

**Key files:** `auth/authorization.py`, `auth/simple_authorization.py`,
`tests/unit/test_authorization_write_protection.py`

---

### 2. Deployment mode + feature service

**Problem:** The codebase assumed a single deployment topology. Differentiating OSS
self-hosted from cloud-managed required scattered `if` checks.

**Decision:** Introduced a `FeatureService` that gates capabilities by deployment mode
(OSS / Cloud / Enterprise). Features are queried by name; the service reads from a
`DEPLOYMENT_MODE` env variable. The extension discovery system plugs into this at startup.

**Key files:** `features/service.py`, `libs/common/agentarea_common/extensions/`

---

### 3. Execution engine abstraction

**Problem:** Temporal was the only supported execution engine, making local development
and integration tests heavyweight.

**Decision:** Introduced `EXECUTION_ENGINE` config (`temporal` | `direct`). `DirectTaskManager`
runs workflow logic in-process without Temporal, using the same interface as
`TemporalTaskManager`. Both implement `TaskManager`. The direct engine is for development
and testing; production uses Temporal.

**Key files:** `application/temporal_workflow_service.py`,
`DirectTaskManager` in execution activities

---

### 4. IaC reconciler

**Problem:** Bootstrapping system entities (model specs, provider configs, MCP servers)
required manual API calls or one-off scripts with no declarative source of truth.

**Decision:** Added a `ReconcilerService` that reads YAML config files and upserts system
entities. An async `reconciler` entrypoint runs it at startup. Config is version-controlled;
the reconciler is idempotent.

**Key files:** `bootstrap/`, reconciler activities, YAML parsers

---

### 5. OpenAPI connections

**Problem:** Agents could only connect to tools via MCP. REST APIs without an MCP wrapper
were inaccessible.

**Decision:** Added an OpenAPI connections library: CRUD for connection specs (stored with
custom headers + secrets), spec parsing (auto-detect OpenAPI 2/3), tool discovery
(each operation becomes a tool), SSRF protection on the URL. The UI unified MCP and OpenAPI
under a single Connections page.

**Key files:** `libs/mcp/`, `api/v1/network.py`,
`agentarea-webapp/src/app/(main)/mcp-servers/`

---

### 6. Progressive skill disclosure + sandbox execution

**Problem:** All skill scripts were exposed to the LLM in the system prompt at once,
consuming tokens regardless of relevance. Scripts ran in the main workflow process
with full environment access.

**Decision:** Skills are now disclosed progressively: the system prompt shows a compact
catalog; the LLM calls `activate_skill` to load a skill's full definition before use.
Script execution runs in a sandboxed subprocess with a restricted environment.

**Key files:** `workflows/agent_execution_workflow.py`, skill activities,
`docs/skill-sandboxing.md`

---

### 7. Dynamic context strategy (see also ADR-001)

**Problem:** Long agent sessions exceeded context windows; large tool outputs crowded
out the active conversation.

**Decision:** Three-tier `ContextStrategy` (`static` / `hybrid` / `dynamic`) gates output
offloading (MinIO), history preservation across compaction, and progressive tool
disclosure. `hybrid` is the system default. See ADR-001 for full rationale.

---

### 8. Pagination + workspace repository hardening

**Problem:** List endpoints returned unbounded result sets. Repository queries lacked
consistent cursor-based pagination.

**Decision:** Added a `Pagination` value object and cursor support to
`WorkspaceScopedRepository`. All list endpoints accept `limit` / `cursor` parameters.

**Key files:** `base/pagination.py`, `base/workspace_scoped_repository.py`

---

### 9. Webhook verification + trigger channel events

**Problem:** Incoming webhooks were accepted without signature verification. Trigger
events had no typed channel event model.

**Decision:** Added `webhook_verification.py` with HMAC-SHA256 signature validation
(configurable secret per trigger). Added `channel_events.py` with typed Pydantic models
for each trigger channel (Slack, GitHub, HTTP).

**Key files:** `triggers/webhook_verification.py`, `triggers/domain/channel_events.py`

---

### 10. Valkey migration

Replaced Redis (Bitnami chart) with Valkey across Helm charts, Docker Compose, and
client configuration. No application-level changes; Valkey is API-compatible.

---

## What Was Explicitly Deferred

The governance primitives analysis identified 21 capabilities across three tiers. This
branch does not implement any of them directly — it only builds the substrate they depend on:

- Policy engine, capability model, RBAC: depend on the authorization layer (now done)
- Rate limiting, token budget: depend on execution engine abstraction (now done)
- Escalation workflow: depends on task manager abstraction (now done)
- MCP tool security scanner: depends on OpenAPI/MCP connections refactor (now done)

The next step is to start on Tier 1 governance primitives from the gap analysis.

## Consequences

- All mutating API endpoints now require WRITER or ADMIN role — clients must send tokens
  with appropriate role claims.
- `EXECUTION_ENGINE=direct` is available for local dev; default remains `temporal`.
- OpenAPI connections share the MCP connection UI — operators see one Connections page
  not two.
- Webhook triggers require a configured secret for signature verification; unsigned
  webhooks are rejected unless verification is explicitly disabled per trigger.
- Context strategy defaults to `hybrid` for all agents and model specs — no behavior
  change for existing deployments.
