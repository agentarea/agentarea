# Audit System Analysis & Recommendations

**Date:** 2026-03-26
**Status:** Analysis complete, pending implementation decision

## Executive Summary

Our current audit system uses Python's `logging` module to write text-formatted audit events to stdout and a rotating log file. This approach has fundamental limitations for a multi-tenant B2B platform: events are not queryable via the API, there's no before/after state tracking for mutations, retention is bounded by file rotation, and querying requires parsing raw log files line-by-line. This document analyzes these problems and compares our approach with industry best practices from AWS CloudTrail, GitHub Audit Log, PostHog, and Sentry.

---

## 1. Current Implementation Analysis

### Architecture Overview

```
API Request → Repository (CRUD) → AuditLogger.log_*() → Python logging.info()
                                                            ├── stdout (StreamHandler)
                                                            └── audit.log (RotatingFileHandler, 10MB x 5)
```

**Key files:**
- `agentarea_common/logging/audit_logger.py` — `AuditLogger` class, `AuditEvent` model, `AuditAction` enum
- `agentarea_common/logging/config.py` — `WorkspaceContextFormatter`, `setup_logging()`
- `agentarea_common/logging/query.py` — `AuditLogQuery` file-based query utility
- `agentarea_common/base/workspace_scoped_repository.py` — audit calls embedded in repository CRUD
- `agentarea_governance/interceptors/observers/audit_observer.py` — governance-level audit observer

### Problem 1: Log-file storage, not database-backed

**Location:** `config.py:121-130` (RotatingFileHandler setup), `audit_logger.py:118-125` (fallback StreamHandler)

The audit system writes to a `RotatingFileHandler` with a 10MB limit and 5 backups. This means:
- **Max ~50MB of audit history retained** — inadequate for compliance (SOC 2 requires 1+ year retention)
- **Events are silently dropped** when the file rotates — no guarantee of delivery
- **No transactional guarantees** — if the app crashes mid-write, events can be corrupted
- **Not accessible in containerized deployments** — container restarts destroy local files

### Problem 2: File-based querying is not scalable

**Location:** `query.py:67-130`

`AuditLogQuery.query_logs()` opens the log file and iterates line-by-line with `json.loads()`. This is:
- **O(n) for every query** — scans the entire file regardless of filters
- **No indexing** — can't efficiently query by workspace, user, time range, or resource
- **Single-machine only** — can't query across replicas or distributed deployments
- **No pagination** — only a `limit` parameter, no offset or cursor

### Problem 3: No before/after state for mutations

**Location:** `audit_logger.py:172-197`

The `log_update()` method accepts `resource_data` and the repository does capture `original_data` as `**additional_context`, but there's no *structured* diff tracking. The before-state ends up buried in an untyped `additional_context` dict rather than a queryable `[{field, before, after}]` array. When an agent's configuration is updated, the audit log has the old and new data as flat blobs but not *which fields changed*. This is critical for:
- **Compliance investigations** — "What did the config look like before the incident?"
- **Change attribution** — "Who changed this field from X to Y?"
- **Rollback decisions** — "What was the previous state?"

### Problem 4: Tight coupling to repository layer

**Location:** `workspace_scoped_repository.py:77-87, 154-166, 224-234, 287-299, 397-407`

Audit logging is embedded directly in the base repository's `get_by_id()`, `list()`, `create()`, `update()`, and `delete()` methods. This creates:
- **Mixed concerns** — persistence logic and audit logging intertwined
- **No service-layer context** — the repository doesn't know the *business operation* (e.g., "deploy agent" vs. "update agent config"), only the CRUD verb
- **Can't audit service-level operations** — multi-step operations (like delegation or A2A task routing) don't get meaningful audit entries
- **Duplicate audit noise** — a single service call that reads 3 entities produces 3 separate "READ" audit events

### Problem 5: Excessive noise from READ/LIST operations

**Location:** `audit_logger.py:13-21` (AuditAction enum includes READ and LIST)

Every `get_by_id()` and `list()` call generates an audit event. In a typical page load:
- List agents → AUDIT: LIST agent
- Get workspace settings → AUDIT: READ settings
- List MCP servers → AUDIT: LIST mcp_server
- Get user profile → AUDIT: READ user

This generates **4+ audit events per page view**, drowning out meaningful mutations (CREATE, UPDATE, DELETE) in noise. Industry best practice is to audit reads only for sensitive resources (secrets, credentials, PII), not all reads.

### Problem 6: No API endpoint for audit log access

There is no REST endpoint for querying audit logs. Users and workspace admins cannot:
- View who made changes to their workspace
- Investigate security incidents
- Export audit logs for compliance
- Filter audit events by time, actor, resource, or action

### Problem 7: Missing request context

**Location:** `audit_logger.py:24-86` (AuditEvent fields)

The audit event captures `user_id` and `workspace_id` but not:
- **Source IP address** — critical for security investigations
- **Request ID / correlation ID** — for tracing an event back to the HTTP request
- **User agent** — distinguishing API calls from UI actions
- **Session ID** — linking events within a single session
- **API key ID** — which credential was used for authentication

### Problem 8: Global singleton pattern

**Location:** `audit_logger.py:306-315`

The `get_audit_logger()` function uses a module-level global `_audit_logger`. This makes testing harder (tests need to reset the global) and prevents configuring different audit loggers for different contexts.

---

## 2. Industry Best Practices Comparison

### AWS CloudTrail

| Aspect | CloudTrail Approach |
|--------|-------------------|
| **Schema** | Structured JSON events with: `eventTime`, `eventSource`, `eventName`, `awsRegion`, `sourceIPAddress`, `userIdentity`, `requestParameters`, `responseElements`, `errorCode` |
| **Storage** | Events stored in S3 (immutable) + CloudWatch Logs + optional Athena for SQL queries |
| **Queryability** | Event history API (90 days), Lake (SQL queries), Athena integration for long-term |
| **Key differentiator** | Separates "management events" (control plane) from "data events" (data plane reads). Management events always on, data events opt-in to control noise |
| **Before/after** | `requestParameters` (what was requested) + `responseElements` (what happened) |

**Lesson for us:** Separate control-plane operations (config changes, deployments) from data-plane operations (reads, list queries). Only audit control-plane by default.

### GitHub Audit Log

| Aspect | GitHub Approach |
|--------|---------------|
| **Schema** | `action` (dotted: `repo.create`, `org.invite_member`), `actor`, `actor_ip`, `created_at`, `org`, `repo`, `user`, `data` (before/after), `transport` |
| **Storage** | Database-backed with streaming to SIEM (Splunk, Datadog) |
| **Queryability** | REST API + GraphQL API with full filtering by action, actor, date range. Streaming API for real-time export |
| **Key differentiator** | Dotted action names (`org.update_member_role`) give both category and specificity. Rich filtering API with `phrase` search |
| **Retention** | 180 days for most orgs, unlimited for Enterprise with audit log streaming |

**Lesson for us:** Use dotted/hierarchical action names (`agent.create`, `agent.deploy`, `mcp.config.update`) instead of generic CRUD verbs. Provide API access with filtering.

### PostHog Activity Log

| Aspect | PostHog Approach |
|--------|----------------|
| **Schema** | `ActivityLog` model with: `team_id`, `organization_id`, `user` (FK), `was_impersonated`, `is_system`, `activity` (verb), `item_id`, `scope` (resource type), `detail` (JSON with `changes[]` array), `created_at` |
| **Storage** | PostgreSQL table (`posthog_activitylog`) with indexes on `team_id`, `scope`, `created_at` |
| **Before/after** | `detail.changes` array: `[{"type": "FeatureFlag", "field": "active", "action": "changed", "before": false, "after": true}]` |
| **Key differentiator** | Explicit `changes[]` array with typed before/after diffs. Distinguishes system vs. user actions. Impersonation tracking |

**Lesson for us:** Store changes as structured diffs with `field`, `before`, `after` per changed field. Use a database table, not log files.

### Sentry Audit Log

| Aspect | Sentry Approach |
|--------|---------------|
| **Schema** | `AuditLogEntry` model with: `organization`, `actor_label`, `actor` (FK to User), `actor_key` (FK to ApiKey), `target_object`, `target_user`, `event` (integer enum), `ip_address`, `data` (JSON), `datetime` |
| **Storage** | PostgreSQL table with organization-scoped queries |
| **Queryability** | REST API: `GET /api/0/organizations/{org}/audit-logs/` with `event`, `actor`, date range filters |
| **Key differentiator** | Tracks both the `actor` (who) AND the auth method (`actor_key` for API key vs `actor` for user). Integer enum for events enables efficient filtering |
| **Retention** | 90 days for Team plan, unlimited for Business/Enterprise |

**Lesson for us:** Track *how* the user authenticated (UI session vs. API key vs. service account). Provide tiered retention.

---

## 3. Pattern Comparison Matrix

| Capability | Our Current | CloudTrail | GitHub | PostHog | Sentry |
|-----------|------------|------------|--------|---------|--------|
| Storage | Rotating log file | S3 + DB | DB | PostgreSQL | PostgreSQL |
| Queryable via API | No | Yes | Yes (REST + GraphQL) | Yes | Yes |
| Before/after diffs | No | Partial | Yes | Yes (structured) | Partial (JSON blob) |
| IP address tracking | No | Yes | Yes | No | Yes |
| Auth method tracking | No | Yes (IAM role/key) | Yes | Yes (impersonation) | Yes (user vs API key) |
| Noise control | No (all CRUD) | Yes (mgmt vs data events) | Yes (only mutations) | Yes (only mutations) | Yes (only mutations) |
| Multi-tenant scoped | Yes (workspace_id) | Yes (account) | Yes (org) | Yes (team + org) | Yes (org) |
| Retention policy | ~50MB then dropped | Configurable | 180d / unlimited | Configurable | 90d / unlimited |
| Real-time streaming | No | Yes (EventBridge) | Yes (streaming API) | No | No |
| Hierarchical actions | No (flat CRUD) | Yes (service.action) | Yes (resource.action) | No (flat verb) | Integer enum |

---

## 4. Recommendations

### R1: Move to database-backed audit storage

Replace the `logging.info()` + `RotatingFileHandler` approach with a dedicated `audit_events` database table.

**Proposed schema:**

```sql
CREATE TABLE audit_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- When
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Who
    actor_id VARCHAR(255) NOT NULL,          -- user_id or service account
    actor_type VARCHAR(50) NOT NULL,         -- 'user', 'service', 'system', 'api_key'
    actor_label VARCHAR(255),                -- display name at time of event

    -- Where
    workspace_id VARCHAR(255) NOT NULL,
    source_ip INET,
    user_agent TEXT,
    request_id VARCHAR(255),                 -- correlation ID

    -- What
    action VARCHAR(100) NOT NULL,            -- hierarchical: 'agent.create', 'mcp.config.update'
    resource_type VARCHAR(100) NOT NULL,     -- 'agent', 'mcp_server', 'trigger', 'skill'
    resource_id VARCHAR(255),
    resource_label VARCHAR(255),             -- human-readable name at time of event

    -- Changes (for mutations)
    changes JSONB,                           -- [{field, before, after}] array

    -- Context
    event_metadata JSONB DEFAULT '{}'::jsonb, -- additional context

    -- Constraints (workspace_id and created_at are already NOT NULL above)
);

-- Query indexes
CREATE INDEX idx_audit_events_workspace_created
    ON audit_events (workspace_id, created_at DESC);
CREATE INDEX idx_audit_events_actor
    ON audit_events (workspace_id, actor_id, created_at DESC);
CREATE INDEX idx_audit_events_resource
    ON audit_events (workspace_id, resource_type, resource_id, created_at DESC);
CREATE INDEX idx_audit_events_action
    ON audit_events (workspace_id, action, created_at DESC);
```

### R2: Use hierarchical action names

Replace flat `AuditAction` enum (CREATE/UPDATE/DELETE/READ/LIST/ERROR) with dotted action strings:

```
agent.create          mcp_server.create        trigger.create
agent.update          mcp_server.update        trigger.fire
agent.delete          mcp_server.delete        trigger.disable
agent.deploy          mcp_server.connect       skill.install
agent.delegate        mcp_server.disconnect    skill.execute
```

This gives both the resource category and the specific operation in one field.

### R3: Stop auditing reads by default

Remove audit logging from `get_by_id()` and `list()` in the base repository. Only audit:
- **All mutations** (create, update, delete)
- **Sensitive reads** (secrets access, credential viewing)
- **Administrative actions** (workspace settings changes, member management)

### R4: Move audit from repository to service layer

Instead of the repository auto-logging every CRUD operation, have services emit audit events at the *business operation* level:

```python
# Instead of repository-level:
#   AUDIT: UPDATE agent  (what field? why?)

# Service-level:
#   agent.deploy — actor deployed agent "my-assistant" to production
#   agent.update_config — actor changed model from gpt-4 to claude-sonnet
```

This captures intent, not just mechanics.

### R5: Add structured change tracking

For every mutation, capture what changed:

```python
changes = [
    {"field": "model", "before": "gpt-4", "after": "claude-sonnet-4"},
    {"field": "temperature", "before": 0.7, "after": 0.3},
]
```

### R6: Add request context via middleware

Create a FastAPI middleware that captures `source_ip`, `user_agent`, `request_id` and makes them available to the audit system via contextvars:

```python
from contextvars import ContextVar

audit_context: ContextVar[dict] = ContextVar('audit_context', default={})

class AuditContextMiddleware:
    async def dispatch(self, request, call_next):
        # Use X-Forwarded-For behind reverse proxy, fall back to direct client
        forwarded = request.headers.get("x-forwarded-for")
        source_ip = forwarded.split(",")[0].strip() if forwarded else request.client.host
        ctx = {
            "source_ip": source_ip,
            "user_agent": request.headers.get("user-agent"),
            "request_id": request.headers.get("x-request-id", str(uuid4())),
        }
        token = audit_context.set(ctx)
        try:
            return await call_next(request)
        finally:
            audit_context.reset(token)
```

### R7: Provide an API endpoint for audit log access

```
GET /v1/audit-logs?workspace_id=...&action=...&actor_id=...&resource_type=...&since=...&until=...&limit=50&cursor=...
```

With cursor-based pagination, workspace scoping, and filtering by action, actor, resource type, and time range.

### R8: Add retention policy support

- Default retention: 90 days (auto-purge via background task)
- Extended retention: 1 year (for paid plans, SOC 2 compliance)
- Export capability: CSV/JSON export for compliance teams

---

## 5. Recommended Migration Path

### Phase 1: Schema & Service (Week 1-2)
1. Create `audit_events` table via Alembic migration
2. Create `AuditService` with `record_event()` method that writes to DB
3. Add `AuditContextMiddleware` for request context capture
4. Define hierarchical action names as string constants

### Phase 2: Migration (Week 3)
1. Replace `AuditLogger.log_event()` to write to both DB and log (dual-write)
2. Move audit calls from repository to service layer, one service at a time
3. Remove READ/LIST audit calls from base repository
4. Add `changes` tracking to service-layer update methods

### Phase 3: API & Cleanup (Week 4)
1. Add `GET /v1/audit-logs` endpoint with filtering and pagination
2. Remove file-based `AuditLogQuery` class
3. Remove `RotatingFileHandler` audit file handler
4. Add retention policy background task
5. Add audit log UI in the webapp

---

## 6. Summary

| Problem | Recommendation | Priority |
|---------|---------------|----------|
| Log-file storage | R1: Database-backed storage | Critical |
| Read/List noise | R3: Stop auditing reads | High |
| Repository coupling | R4: Service-layer audit | High |
| No before/after | R5: Structured change tracking | High |
| Flat CRUD actions | R2: Hierarchical action names | Medium |
| Missing request context | R6: Middleware context capture | Medium |
| No API access | R7: Audit log API endpoint | Medium |
| No retention policy | R8: Configurable retention | Low (until compliance) |

The core shift is from **"log everything at the persistence layer"** to **"record meaningful business events in the database."** This aligns with how every major platform (GitHub, AWS, PostHog, Sentry) approaches audit logging.
