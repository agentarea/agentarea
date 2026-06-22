# ADR: A2A Protocol Transport — Correct Result Flow & v1.0.0 Conformance

**Date:** 2026-06-20
**Status:** Accepted — implemented 2026-06-20 (clean cutover to A2A v1.0.0)
**Deciders:** Engineering team
**Related plans:** `docs/plans/2026-03-10-a2a-spec-compliance.md`, `docs/plans/2026-03-10-agent-delegation-remote-mcp.md`
**Supersedes (doc):** `docs/agent-communication.md` (describes the retired ADK / `InMemoryTaskManager` delegation model)

---

## Context

An audit of our A2A (Agent2Agent) implementation surfaced two classes of problem: a broken
result flow, and significant drift from the protocol schema. We fixed the result flow first,
then performed a **clean cutover from A2A v0.3.0 to the current v1.0.0** wire format (no
dual-version support, no deprecated aliases).

### 1. The result-flow was broken — A2A returned no agent output at all

A2A is, architecturally, **just another transport into the task/event system** — the
same system that powers inbound/outbound **channels** (Telegram/Slack/Discord). But the
A2A layer was written against *assumed* task/event shapes that do not match what the
execution engine actually produces:

- **Non-streaming** (`GetTask`, `SendMessage` response): `convert_agent_task_to_a2a_task`
  (`agents_a2a.py`) always set `artifacts=None`, `history=None`, `status.message=None` and
  ignored `AgentTask.result`. The canonical final answer
  (`task.result["response"]`, produced by the Temporal workflow's `state.final_response`,
  see `temporal_orchestrator.get_workflow_status`) was never mapped onto the wire. A caller
  could poll a `COMPLETED` task forever and never receive output.
- **Streaming** (`SendStreamingMessage`, `SubscribeToTask`): the handler matched event types
  `workflow.task_completed` / `task_completed` and `"llm_response"`. The real events emitted
  by `publish_workflow_events_activity` and surfaced by `EventStreamService` are
  `workflow.WorkflowCompleted` / `workflow.WorkflowFailed` / `workflow.WorkflowCancelled`
  and `workflow.LLMCallChunk` (incremental text in `event_data["original_data"]["chunk"]`).
  **No real event ever matched**, so streaming emitted neither incremental artifacts nor a
  terminal event.
- **Delegation** (`A2AAgentTool`): sends a message and immediately reads `task.artifacts` /
  `status.message`. Since the send is *non-blocking* and returns a non-terminal `Task` (see
  below), and the retrieval path did not map results, agent-to-agent delegation always
  returned `"(No output from agent)"`.

These are the canonical event/result facts the A2A layer MUST align to (verified in code):

| Concept | Source of truth |
|---|---|
| Final answer (completed task) | `task.result["response"]` via `TaskService.get_task_with_workflow_status` |
| Final answer (event) | `workflow.WorkflowCompleted` → `event_data["original_data"]["result" or "final_response"]` |
| Incremental output | `workflow.LLMCallChunk` → `event_data["original_data"]["chunk"]` |
| Terminal events | `workflow.WorkflowCompleted` / `WorkflowFailed` / `WorkflowCancelled` |
| Failure detail | `task.error_message` / workflow status `error` |
| Channel correlation | `task.task_parameters["channel_origin"]` |
| Canonical task entry point | `TaskService.create_and_execute_task_with_workflow` / `submit_task` |

### 2. Version & spec drift — cutover to A2A v1.0.0

Non-blocking send is **not** a bug: the spec allows a message send to return a *non-terminal*
`Task` for long-running work, with the client retrieving the result via task polling,
subscription, or push notifications. Forcing the HTTP request to block until the agent
finishes would time out behind proxies/load-balancers — exactly the failure mode we must
avoid. So we keep send non-blocking and make the **retrieval paths** work.

Beyond that, the implementation targeted a stale, partially-invented mix of v0.3.0. Rather
than patch toward v0.3.0 and carry deprecated aliases, we cut **cleanly over to v1.0.0**,
the current normative release. v1.0.0 is Protobuf-normative and changes the JSON wire in
ways that are incompatible with 0.3.0, so a dual-version shim would have been pure overhead
for a surface with no external 0.3.0 clients yet. Key v1.0.0 wire differences adopted:

- **Methods are PascalCase** RPC names: `SendMessage`, `SendStreamingMessage`, `GetTask`,
  `CancelTask`, `SubscribeToTask`, `ListTasks`, `CreateTaskPushNotificationConfig`,
  `GetTaskPushNotificationConfig`, `ListTaskPushNotificationConfigs`,
  `DeleteTaskPushNotificationConfig`, `GetExtendedAgentCard` (replacing the slash-style
  `message/send`, `tasks/get`, … names).
- **No `kind` discriminators.** `Task`, `Message`, `Part`, and streaming events drop the
  `kind` field entirely (the Protobuf `oneof` carries the discriminator structurally).
- **`Part` is flat:** a part holds `text` *or* `data` *or* `raw`/`url` with `mediaType` —
  no nested `TextPart`/`FilePart`/`DataPart` wrappers, no `kind`.
- **`Message.role`** is the enum `USER` / `AGENT` (uppercase).
- **`TaskState`** uses SCREAMING_SNAKE values: `SUBMITTED`, `WORKING`, `COMPLETED`,
  `FAILED`, `CANCELED`, `INPUT_REQUIRED`, `REJECTED`, `AUTH_REQUIRED`, and
  `TASK_STATE_UNSPECIFIED`.
- **Streaming** uses the `StreamResponse` `oneof`: each frame wraps exactly one of `task`,
  `statusUpdate`, or `artifactUpdate`. The 0.3.0 `final` boolean is gone (terminal is
  conveyed by the terminal `TaskState`).
- **`AgentCard`** advertises transports via `supportedInterfaces[]` (each entry =
  `{url, protocolBinding, protocolVersion:"1.0"}`, first is preferred); there is no
  top-level `url` / `protocolVersion` / `preferredTransport` / `additionalInterfaces`. The
  extended-card flag moves into `capabilities.extendedAgentCard`; `stateTransitionHistory`
  is removed; `provider.url` and per-skill `tags` are required.
- **`A2A-Version` header** is part of v1.0.0: absent ⇒ treated as `1.0`; a non-`1.x`
  version ⇒ `-32009 VersionNotSupportedError`.
- **Error codes:** `-32007` = `ExtendedAgentCardNotConfiguredError`,
  `-32008` = `ExtensionSupportRequiredError`, `-32009` = `VersionNotSupportedError`.

---

## Decision

**Treat A2A as a first-class transport over the existing task/event system, reuse the
canonical result-extraction the channels already rely on, and speak A2A v1.0.0 on the wire.
Do not invent A2A-specific task or event semantics, and do not carry 0.3.0 compatibility.**

### D1 — One canonical `AgentTask → A2A Task` mapping

A single helper builds the A2A `Task` for every non-streaming response (`GetTask`,
`SendMessage`, `CancelTask`, `ListTasks`, delegation):

- `id = str(task.id)`, `contextId =` a stable non-null context id (derive from
  `task.metadata["a2a_context_id"]` if present, else `str(task.id)`). No `kind` field.
- `status.state` mapped from `task.status` to the v1.0.0 `TaskState` enum (covers all states).
- On terminal success: emit `artifacts = [Artifact(artifactId=…, parts=[{text: <final>}])]`
  where `<final> = task.result.get("response")` (fallback `final_response` / stringified).
  Mirror the text into `status.message` (role `AGENT`) so spec-minimal clients that only read
  `status.message` still work.
- On failure: put `task.error_message` into `status.message`.

### D2 — Streaming consumes the real event stream

`SendStreamingMessage` and `SubscribeToTask` map the actual events onto the `StreamResponse`
`oneof`:

- first frame = `task` (the initial Task object).
- incremental = `event_type == workflow.LLMCallChunk` → an `artifactUpdate` frame carrying
  `original_data["chunk"]`.
- terminal = `event_type in {workflow.WorkflowCompleted, workflow.WorkflowFailed, workflow.WorkflowCancelled}`
  → a final `artifactUpdate` with the final text from `original_data["result"|"final_response"]`,
  then a terminal `statusUpdate` with the terminal `TaskState` (no `final` boolean).
- all event payloads are read from `event_data["original_data"]`.

The mapping (`map_workflow_event_to_sse`) is shared with push delivery so streaming and
channels stay in lockstep.

### D3 — Delegation polls for the terminal result

`A2AAgentTool.execute` sends `SendMessage`, then **polls `GetTask`** on the same `/rpc`
endpoint until the task reaches a terminal state or a bounded budget elapses (default
≤ 110 s, under the 120 s activity timeout). It then extracts text via the same artifact/
status-message logic (flat parts: text if `text` is present, data if `data` is present).
HTTP requests stay short; waiting is a series of polls — no long-held connection to time
out. (Subscription via `SendStreamingMessage` remains a future optimization.)

### D4 — A2A v1.0.0 conformance (clean cutover)

- All methods renamed to the v1.0.0 PascalCase set; the 0.3.0 slash-style names are removed,
  **no deprecated aliases**.
- Wire types migrated: drop all `kind` fields; flatten `Part`; uppercase `Message.role`;
  SCREAMING_SNAKE `TaskState`; `StreamResponse` `oneof` frames without `final`.
- `AgentCard` restructured to `supportedInterfaces[]` + `capabilities.extendedAgentCard`,
  required `provider.url` and per-skill `tags`; top-level `url`/`protocolVersion`/
  `preferredTransport` removed.
- Enforce the `A2A-Version` header (absent ⇒ 1.0; non-1.x ⇒ `-32009`); accept
  `application/a2a+json` (and JSON-RPC) request bodies.
- Adopt the v1.0.0 error codes (`-32007`/`-32008`/`-32009`).

### Non-goals (deferred)

- gRPC / HTTP+JSON transports (v1.0.0 requires only one; JSON-RPC stays primary).
- Async fan-out / supervisor delegation (tracked in the resilience plan).
- A2A protocol extensions (`-32008` is wired but no extension is required yet).

---

## Consequences

- A2A `GetTask` / `SendMessage` / streaming return real agent output; agent-to-agent
  delegation works end-to-end.
- A2A and channels share one result-extraction / event-mapping code path → they cannot
  drift again.
- The wire format matches A2A v1.0.0 for the implemented method set; there is a single
  protocol version to reason about (no 0.3.0 compatibility surface).
- Existing 0.3.0 callers (if any) break by design — acceptable given no external 0.3.0
  consumers and the incompatibility of the two wire formats.
- This ADR is the authoritative description of how a task result is returned to an A2A
  caller; `docs/agent-communication.md` is retired and should be rewritten to point here.
