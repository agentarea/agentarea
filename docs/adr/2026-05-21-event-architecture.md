# ADR-002: Event Architecture — Transactional Outbox + Relay

**Date:** 2026-05-21
**Status:** **Superseded** (same day, before any implementation)
**Deciders:** Engineering team
**Related plan:** `~/.claude/plans/rosy-roaming-rabin.md`

> **Supersession note (2026-05-21, revised 2026-05-26):** This ADR proposed a generic
> `event_outbox` + relay + `processed_events` foundation. After review, the design was
> rejected as YAGNI for the current state of the project: there is exactly ONE consumer
> (channel delivery) that needs the durability guarantees, and building generic
> multi-subscriber fanout infrastructure for hypothetical future consumers is
> over-engineering. OSS users already require Redis; enterprise users who want Kafka
> would swap the broker inside a single consumer class — in both deployments a PG
> `event_outbox` would be dead weight.
>
> **What actually shipped (so far):** `channel_inbox` table for inbound webhook dedup
> (migration `ss1_add_channel_inbox`). The original outbound durability design that
> followed this ADR (Redis Streams + a dedicated `messages` projection table +
> DeliveryReconciler) is **not** in tree and **will not be built as specified**.
> Adding a new top-level `messages` table for a single consumer was judged the same
> kind of YAGNI as the generic event_outbox — existing infrastructure (Temporal
> history, `task_events`, `channel_inbox`, Redis Streams PEL if/when used) covers
> durability and observability without a separate projection.
>
> The final outbound delivery design is open and will be decided when the work
> resumes. This ADR is preserved as a reference for the generic event_outbox pattern
> in case a real multi-subscriber demand emerges later.

---

## Context

The platform currently has **nine independent event producers** publishing directly to Redis pub/sub without durability:

| Producer | File |
|---|---|
| Workflow events | `libs/execution/.../activities/agent_execution_activities.py:894` |
| MCP server events | `libs/mcp/.../application/service.py` |
| Trigger events | `libs/triggers/.../trigger_service.py` |
| MCP instance events | `libs/mcp/.../activities/mcp_instance_activities.py` |
| Agent CRUD events | `libs/agents/.../application/agent_service.py` |
| Task lifecycle events | `libs/tasks/.../domain/base_service.py` |
| Governance audit | `libs/governance/.../interceptors/observers/audit_observer.py` |
| LLM model events | `libs/llm/.../application/model_instance_service.py` |
| Generic publisher | `libs/execution/.../activities/event_publisher.py` |

None of them write to a durable event log before publishing. Each is a single-point-of-failure for its category — if the subscriber is offline or Redis pub/sub drops the message, the event is lost.

Two parallel event-shape registries already exist (`agentarea_common/events/event_models.py` and `agentarea_execution/workflows/events.py`) with diverging field schemas, manual conversion code (`event_to_dict`, `to_envelope`, `EventEnvelope.from_any`, `from_dict`), and lossy bridges in `publish_workflow_events_activity` that repackage with `f"workflow.{event_type}"` prefix.

A partial outbox already exists for **workflow events only**: `task_events` table persists each workflow event before publishing to Redis. SSE consumers read from that table on reconnect. But:

- Only workflow events go through it — the other eight producers bypass it entirely.
- The write is **not transactional** with the workflow's business state commit (separate session).
- It has no consumer cursor or dedup table — replay is ad-hoc.

This fragmentation already produced the bug being fixed under this initiative: **agent tasks marked complete in Temporal while outbound Telegram messages never reached users**, because `ChannelRouter._dispatch` catches adapter errors, logs them, and continues. No retry, no dead-letter, no visibility — and no durable record that anyone tried to send anything.

The same class of bug can hit any of the nine producers any time a downstream subscriber is offline.

---

## Decision

Adopt the **transactional outbox pattern** as the canonical event mechanism for the platform.

1. **`event_outbox` table** — append-only durable log. Every domain event is written here as part of the same transaction as the business state change that emits it.
2. **Relay process** (in `apps/worker`) — periodic `SELECT FOR UPDATE SKIP LOCKED` poll publishes outbox rows to the broker and marks them dispatched.
3. **Consumers subscribe to the broker independently.** ChannelDeliveryConsumer, SSE, audit, governance, webhooks — each maintains its own cursor.
4. **`processed_events(consumer, event_id)` table** — consumer-side idempotency. Each consumer records what it has processed; duplicate deliveries are no-ops.
5. **Versioned envelope** — `data_schema_version: "v1"` field on every event. Schema evolution proceeds by adding fields (backwards-compatible) or minting a new event type (breaking).
6. **Temporal remains the orchestration engine.** Workflow activities write to `event_outbox` (transactional with any state change in the same activity). Temporal does not become the queue for event fanout.

This is **not full event sourcing.** State tables remain the source of truth for current state. Events are a side-channel for fan-out and integration. No projection rebuild, no event replay-to-derive-state.

---

## Options Evaluated

| Option | Why considered | Rejected because |
|---|---|---|
| **Status quo** (9 direct Redis pub/sub publishers) | Zero new code. | Already producing the bug we are fixing. Cannot reason about delivery, no replay, no consumer dedup. |
| **Temporal activity per side effect with RetryPolicy** | Use what we already pay for. Less code (~200 LOC vs ~500). | Doesn't generalize: each new consumer becomes a new workflow signal or activity. Workflow stays alive for retry windows (hours), bloating history. Couples future features (SecretField, audit fan-out, webhook integrations) to workflow lifecycle. Same fragmentation as today, just dressed up. |
| **Full event sourcing** (events as source of truth, state derived) | Conceptually pure. Time travel debugging. | Overkill for our domain. Forces every state change through events. Heavy operational tax (schema versioning forever, replay-to-rebuild projections, mental model burden). Wrong tool — we want fan-out, not derive-state. |
| **Direct Kafka with idempotent producer** | Industry standard. Native at-least-once, partitioned, durable. | Adds a hard infra dependency to OSS distribution. Most OSS users don't run Kafka. Solves a problem we don't have (>10k events/s). |
| **Transactional outbox + relay** ✓ | Generalizes across all 9 producers, no new infra (uses existing PG), enables future Kafka swap via relay backend. | **Chosen** — see below. |

---

## Chosen: Transactional Outbox + Relay

### Tables

```sql
event_outbox (
  id                   BIGSERIAL PRIMARY KEY,
  event_id             UUID NOT NULL UNIQUE,
  event_type           VARCHAR(128) NOT NULL,
  data_schema_version  VARCHAR(16) NOT NULL DEFAULT 'v1',
  aggregate_id         VARCHAR(255),
  aggregate_type       VARCHAR(64),
  workspace_id         VARCHAR(255),
  correlation_id       VARCHAR(255),
  payload              JSONB NOT NULL,
  created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
  dispatched_at        TIMESTAMPTZ,
  dispatch_attempts    INTEGER NOT NULL DEFAULT 0,
  last_error           TEXT
);
CREATE INDEX idx_event_outbox_undispatched
  ON event_outbox (id) WHERE dispatched_at IS NULL;
CREATE INDEX idx_event_outbox_workspace ON event_outbox (workspace_id);

processed_events (
  consumer    VARCHAR(64) NOT NULL,
  event_id    UUID NOT NULL,
  processed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (consumer, event_id)
);
```

### Envelope

```python
class EventEnvelope(BaseModel):
    event_id: UUID
    event_type: str
    data_schema_version: str = "v1"
    timestamp: datetime
    aggregate_id: str | None
    aggregate_type: str | None
    workspace_id: str | None
    correlation_id: str | None
    data: dict[str, Any]
```

`event_models.py` becomes authority; `workflows/events.py` retires (consolidation work captured separately).

### Producer pattern

```python
async with session.begin():
    await save_business_state(session, ...)
    await event_outbox_repo.append(
        session,
        event_type="AgentReplyEmitted",
        aggregate_id=task_id,
        aggregate_type="task",
        workspace_id=workspace_id,
        payload={...},
    )
# COMMIT — either both write or neither writes
```

### Relay

Lives in `apps/worker`. One per process; horizontally scaled via `SELECT FOR UPDATE SKIP LOCKED`:

```sql
SELECT * FROM event_outbox
WHERE dispatched_at IS NULL
ORDER BY id
LIMIT 100
FOR UPDATE SKIP LOCKED;
```

For each row: publish to broker (Redis pub/sub today, swappable to Kafka), `UPDATE event_outbox SET dispatched_at = now()`. On publish failure: leave `dispatched_at = NULL`, increment `dispatch_attempts`, record `last_error`. Next poll retries.

### Consumers

Each consumer is an async loop in `apps/worker` subscribed to its broker channel(s):

```python
async for envelope in broker.subscribe(channels=["agentarea.events.workflow.*"]):
    if await processed_events.exists("channel_delivery", envelope.event_id):
        continue  # dup, skip
    try:
        await handle(envelope)
        await processed_events.record("channel_delivery", envelope.event_id)
    except RetryableError:
        # rely on broker redelivery / relay republish on next tick
        raise
```

`ChannelDeliveryConsumer`, `SSEConsumer`, `AuditConsumer`, future `WebhookConsumer`, etc., all follow this shape.

### Versioning

Breaking changes mint a new event type (`AgentReplyEmittedV2`). Backward-compatible changes (new optional fields) keep `data_schema_version="v1"`. Major bump means consumers add a handler for the new type before producers emit it.

---

## Consequences

### Positive

- **Atomic with business state.** Producers can never publish an event for state that wasn't committed, or commit state without publishing.
- **Multi-consumer fan-out is cheap.** Adding a webhook integration is a new consumer file, not a producer-side change.
- **Replay and audit by SQL.** `SELECT * FROM event_outbox WHERE workspace_id = $1 AND created_at > $2` answers every "what happened" question.
- **Consumer idempotency formalized.** `processed_events` makes duplicate delivery a no-op, not a bug.
- **Schema evolution has a story.** `data_schema_version` + new-type-on-break is documented, not folklore.
- **Broker-swappable.** Relay's publish path can move from Redis pub/sub to Redis Streams to Kafka without touching producers or consumers.

### Negative

- **~400-600 LOC of foundation code** vs ~200 for a Temporal-only approach for the same single bug fix today.
- **Relay process to operate.** Needs lag monitoring, dead-letter handling once `dispatch_attempts` exceeds threshold.
- **`event_outbox` row growth.** Requires partitioning by `workspace_id` once volume warrants, and a retention job (drop dispatched rows older than N days).
- **Eventual consistency between commit and broker.** Workflow completes; the SSE update can be 100ms-1s behind. Acceptable for our domain.

### Neutral but worth noting

- Eight existing producers must migrate to the outbox pattern. Done incrementally (each becomes a small PR); old direct-publish path stays alive until each migrates.
- `task_events` table is subsumed by `event_outbox` (workflow events become rows there). Migration path: dual-write during transition, then retire `task_events`.

---

## What this is NOT

- **Not full event sourcing.** State tables remain canonical for current state.
- **Not a generic message bus.** This is for domain events emitted by our services, consumed by our services. External integrations layer on top via dedicated consumers.
- **Not a replacement for Temporal.** Temporal is still the orchestration engine for multi-step agent workflows. Events emitted *from* Temporal activities write to the outbox in the same activity; Temporal does not become the queue.
- **Not a hard dependency commitment to Redis.** Relay's broker is pluggable. Today it publishes to Redis pub/sub (matching existing wire format); tomorrow it can publish to Redis Streams or Kafka with no producer/consumer code changes.

---

## Migration order

1. **Bridge consolidation** — merge `event_models.py` and `workflows/events.py` into one canonical Pydantic registry.
2. **`event_outbox` + `processed_events` migrations** — tables only, no producers wired yet.
3. **Relay process in `apps/worker`** — reads outbox, publishes to broker, marks dispatched.
4. **First producer migration: workflow events.** `publish_workflow_events_activity` writes to outbox instead of (or in addition to) direct Redis publish. `task_events` retire path planned.
5. **ChannelDeliveryConsumer.** Subscribes to broker, dispatches via adapter, uses `processed_events` for dedup. Closes the original outbound-loss bug.
6. **Eight remaining producers migrate to outbox**, one PR each, low risk (producer changes one call).
7. **Retire `task_events`** once nothing reads from it.

The original channel runtime work (this conversation's Phase 1 — `channel_inbox` + InboundDispatcher) is **unchanged** by this ADR. Inbound durability is a separate concern from event fan-out and remains as-built.
