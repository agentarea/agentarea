# Event System and Execution Architecture Improvements Plan

This document captures a prioritized plan to harden the event-driven architecture, standardize schemas, decouple infrastructure, and improve runtime execution (SSE streaming, workflow orchestration, and reliability).

## Goals

- Decouple business logic from transport (Redis/FastStream) via a strong EventBroker abstraction.
- Standardize and validate event schemas (versioned, evolvable).
- Improve scalability and reliability of SSE streaming.
- Separate API from event consumer/worker responsibilities.
- Enhance observability and operational safety.
- Reduce coupling to internal broker attributes and implementation details.
- Improve execution workflow (Temporal) and end-to-end delivery guarantees.

## Current Pain Points

- Leaky abstraction: consumers directly access Redis internals (private attributes) instead of using a broker API.
- Inconsistent event payload schemas; handlers parse multiple shapes defensively.
- API layer includes orchestration (Temporal) in FastStream subscribers.
- Broker lifecycle and cleanup rely on private attributes.
- SSE stream risks: unbounded queues, per-connection pubsub, weak cancellation.
- Over-broad subscriptions (e.g., `workflow.*`) with client-side filtering.
- Mixed logging (print + logger) and inconsistent SSE error envelopes.
- Missing reliable transactional publish + persist pattern for events.

## Guiding Principles

- Clean Architecture: domain and application layers independent of transport or frameworks.
- Strong contracts: versioned, validated event schemas; single source of truth for formatting.
- Observable by default: metrics, logs, and traces on critical paths.
- Resilience first: backpressure, retries, idempotency, and graceful degradation.
- Incremental migration: adapters and compatibility layers where needed.

---

## Roadmap

### Phase 1: Contracts and Abstractions (High Priority)

1) EventBroker Subscribe/Consume API
- Deliverables:
  - Extend EventBroker with subscribe(pattern|topic), unsubscribe, and async iterator/handler APIs.
  - Redis implementation that hides FastStream/Redis internals.
  - Tests: unit + integration for publish/subscribe lifecycle and cancellation.
- Acceptance Criteria:
  - No direct access to private broker fields in consumers.
  - SSE streaming consumes exclusively via EventBroker.

2) Standardized Event Schemas
- Deliverables:
  - Canonical envelope (CloudEvents-like): id, type, time, source, subject, specversion, datacontenttype, data.
  - Pydantic models for key events (TaskCreated, WorkflowStarted, WorkflowCompleted, Errors).
  - Validation at publish and at consume boundaries; clear error handling for invalid messages.
  - Versioning for event types (e.g., `workflow.task.created.v1`).
- Acceptance Criteria:
  - Handlers no longer parse multiple shapes; they accept one validated model.
  - Publishers cannot emit invalid events (tests enforce validation).

3) Topic Routing and Filtering
- Deliverables:
  - Adopt specific routing keys (e.g., `workflow.{task_id}`) instead of `workflow.*` catch-all filters.
  - Update publishers accordingly.
- Acceptance Criteria:
  - SSE consumers subscribe only to the exact topics needed.

### Phase 2: Streaming and Worker Separation (High Priority)

4) SSE Streaming Hardening
- Deliverables:
  - Use bounded asyncio.Queue with backpressure strategy (e.g., drop-oldest or block producer).
  - Proper cancellation and cleanup when clients disconnect.
  - Heartbeats/keepalive and idle timeouts.
  - Unified SSE formatting function for id, event, data; consistent error event envelopes.
- Acceptance Criteria:
  - No resource leaks under load tests.
  - Consistent SSE message contract across all event types.

5) Separate Event Handlers into Worker Service
- Deliverables:
  - Move FastStream subscribers (e.g., TaskCreated → Temporal start) from API into a worker process/package.
  - Clear bootstrap for workers; API only publishes/brokers and exposes read endpoints.
- Acceptance Criteria:
  - API restart does not affect worker consumption.
  - Independent scaling and deployment for workers.

### Phase 3: Reliability, Observability, and Persistency (Medium Priority)

6) Broker Lifecycle and Cleanup
- Deliverables:
  - Public lifecycle methods on EventBroker (connect, close, status) used by API and worker; no private attribute access.
- Acceptance Criteria:
  - Clean startup/shutdown without relying on internal broker details.

7) Historical Events + Live Stream
- Deliverables:
  - Standard path to read historical events from event store (DB/log) before switching to live broker stream.
  - Optional resume tokens/offsets for pagination and reconnection.
- Acceptance Criteria:
  - Include-history flow is consistent and ordered; tested with pagination/reconnect scenarios.

8) Observability and Metrics
- Deliverables:
  - Structured logs with contextual fields (task_id, agent_id, event_type).
  - Metrics for queue depth, dropped events, consumer lag, broker connections, SSE connection count, handler latency, errors.
- Acceptance Criteria:
  - Dashboards and alerts for hot paths; performance baselines and SLOs defined.

### Phase 4: Execution Reliability and Safety (Medium Priority)

9) Transactional Outbox and Idempotency
- Deliverables:
  - Outbox pattern for “persist + publish” to avoid message loss.
  - Idempotent event handling (dedupe by event id/key).
- Acceptance Criteria:
  - Verified at-least-once semantics without creating duplicates downstream.

10) Temporal Workflow Hardening
- Deliverables:
  - Idempotent workflow IDs; retries and timeouts on activities; heartbeats; cancellation paths; versioning for workflow changes.
  - Signals/queries for control and monitoring (pause, resume, cancel).
- Acceptance Criteria:
  - Execution remains correct with partial failures and restarts; tests cover timeouts, cancellations, and retries.

---

## Dependencies and Risks

- Changing event schemas requires coordinated rollout (publishers and consumers). Use versioned topics/types and temporary adapters.
- Replacing direct Redis access with EventBroker subscribe APIs requires careful testing of cancellation and backlog behavior.
- Worker separation changes deployment topology; ensure CI/CD and infra scripts are updated.

---

## Testing Strategy

- Unit tests for schema validation and broker API.
- Integration tests for publish/subscribe lifecycle and SSE under load (with disconnects).
- End-to-end tests for TaskCreated → Temporal workflow → Workflow events → SSE clients.
- Chaos tests: broker restarts, slow consumers, network blips.

---

## Suggested Execution Order

1) Define schemas and broker subscribe API (Phase 1).
2) Update SSE to consume through EventBroker with bounded queues (Phase 2).
3) Move event handlers into worker service (Phase 2).
4) Tighten lifecycle + topic routing (Phases 1 & 3).
5) Add observability + historical replay (Phase 3).
6) Implement outbox and Temporal hardening (Phase 4).

---

## Tracking Tasks (Checklists)

- [ ] Event envelope and Pydantic models created and validated (v1).
- [ ] EventBroker subscribe/consume APIs implemented (Redis).
- [ ] Publishers updated to topic-specific routing keys.
- [ ] SSE refactored to use EventBroker with bounded queues and proper cancellation.
- [ ] Worker service runs event handlers independently of the API.
- [ ] Broker lifecycle no longer uses private attributes.
- [ ] Historical + live streaming path implemented with ordering and resume.
- [ ] Metrics and structured logging added to hot paths.
- [ ] Outbox and idempotent handling implemented.
- [ ] Temporal workflow reliability features (retries, timeouts, heartbeats, cancellation, versioning) in place.