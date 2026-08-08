---
title: Stream task events
type: guide
summary: Consume a task's live event feed over SSE, or page its durable history, without losing events that fired before you attached.
prerequisites:
  - /concepts/execution/events
related:
  - /guides/tasks/start-a-task
  - /guides/tasks/debug-a-failed-task
  - /concepts/execution/tasks
last_updated: 2026-07-29
---

# Stream task events

Do this when you want to render or follow a run as it happens. Do not build a
polling loop against `GET /v1/agents/{agent_id}/tasks/{task_id}` for this — the
stream already replays everything from the beginning, so attaching late loses
nothing.

## Prerequisites

- A task id and its agent id. See [Start a task](/guides/tasks/start-a-task).
- An API key.
- A client that can hold an open HTTP response. `curl -N` works; `curl` without
  `-N` buffers and looks hung.

## Choose an endpoint

| Option | Pick it when |
|---|---|
| `GET /v1/agents/{agent_id}/tasks/{task_id}/events/stream` | You want live updates. Replays full history, then tails. Ends on a terminal event. |
| `GET /v1/agents/{agent_id}/tasks/{task_id}/events` | You want a finished task's history, paginated, in one request. |
| `POST /v1/agents/{agent_id}/tasks/` | You are starting the task anyway and want the stream on the same connection. |

## Steps

### Stream live

```bash
curl -N "$AGENTAREA_URL/v1/agents/$AGENT_ID/tasks/$TASK_ID/events/stream" \
  -H "Authorization: Bearer $AGENTAREA_TOKEN" \
  -H "Accept: text/event-stream"
```

Each frame is a standard SSE event. The SSE event name and the payload's
`event_type` are the same dotted string, so a consumer can key on either:

```
event: connected
data: {"task_id": "3f2a...", "agent_id": "9b1d...", "execution_id": "task-3f2a...", "message": "Connected to task event stream", "timestamp": "2026-07-29T10:15:04.881233+00:00"}

event: llm.call.started
data: {"event_type": "llm.call.started", "event_id": "0f7c...", "timestamp": "...", "data": {"task_id": "3f2a...", "execution_id": "task-3f2a...", "iteration": 1}}

event: tool.call
data: {"event_type": "tool.call", "event_id": "1a2b...", "timestamp": "...", "data": {"tool_call_id": "call_abc", "tool_name": "bash", ...}}

event: task.completed
data: {"event_type": "task.completed", "event_id": "9e8d...", "timestamp": "...", "data": {"success": true, "message": "...", "validation_state": "passed"}}
```

The feed replays the task's full durable history first, then tails live events,
de-duplicating by `event_id` across the hand-off. It closes after
`task.completed`, `task.failed`, or `task.cancelled`.

### Drop token-level chunks

`llm.call.chunk` events are high volume — one per token. They are included by
default. Turn them off when you only need structural progress:

```bash
curl -N "$AGENTAREA_URL/v1/agents/$AGENT_ID/tasks/$TASK_ID/events/stream?include_chunks=false" \
  -H "Authorization: Bearer $AGENTAREA_TOKEN"
```

### Read history instead

```bash
curl -s "$AGENTAREA_URL/v1/agents/$AGENT_ID/tasks/$TASK_ID/events?page=1&page_size=50" \
  -H "Authorization: Bearer $AGENTAREA_TOKEN" | jq '{total, has_next, first: .events[0]}'
```

```json
{
  "total": 42,
  "has_next": false,
  "first": {
    "id": "0f7c...",
    "task_id": "3f2a...",
    "agent_id": "9b1d...",
    "execution_id": "task-3f2a...",
    "timestamp": "2026-07-29T10:15:04.912004+00:00",
    "event_type": "task.started",
    "message": "",
    "metadata": {}
  }
}
```

Filter with `?event_type=tool.call`. Chunks never appear here — they are
stream-only and are not persisted.

### Write the consumer correctly

Two rules keep a consumer from breaking when the vocabulary grows:

1. **Do not switch on every event name.** Pass unknown types through. New event
   types are added without a version bump.
2. **Only three types are terminal**: `task.completed`, `task.failed`,
   `task.cancelled`. Stop on those and nothing else.

To collapse a model call or a tool call into one UI element rather than four
lines, group by part id: `tool_call_id` for tool events,
`{execution_id}:{iteration}` for LLM events. A later event with the same part id
replaces the earlier one.

## Verify

Confirm the stream terminates on its own with a terminal event rather than
hanging:

```bash
curl -N -s "$AGENTAREA_URL/v1/agents/$AGENT_ID/tasks/$TASK_ID/events/stream?include_chunks=false" \
  -H "Authorization: Bearer $AGENTAREA_TOKEN" | grep -m1 -E '^event: task\.(completed|failed|cancelled)'
```

```
event: task.completed
```

The command exits as soon as the terminal frame arrives. If it exits with no
output, the task produced no terminal event within the feed's limits — see
below.

## Troubleshooting

**The connection opens and nothing appears.** Without `-N`, curl buffers the
response. Add `-N`. If frames still do not arrive, confirm the task actually
dispatched: a task with `execution_id: null` never started a workflow and will
never emit events.

**The stream closes after about 30 minutes with no terminal event.** The feed
has a 30-minute wall-clock limit so a stuck task does not tail forever. This is
the feed giving up, not the task ending. Re-attach, or check
`GET .../tasks/{task_id}` for the current status.

**A completed task streams its history and then hangs briefly before closing.**
Expected. The reader replays from the database, then attaches to the live tail
and waits for a terminal event it may have already replayed. It closes on the
replayed terminal event.

**Events are missing from history but were seen live.** The event was published
to the live stream but its database write failed; that failure is recorded and
does not retry. The live tail is also best-effort in the other direction — a
failed publish leaves the event in history only. History is the durable copy;
prefer `GET .../events` when completeness matters.

**A `blocked` task never emits `task.blocked`.** There is no such event type. A
blocked task emits `task.failed` on the feed while its row reads `blocked`. Read
`failure_reason` from the task to tell them apart.

## Related

- [Events](/concepts/execution/events)
- [Debug a failed task](/guides/tasks/debug-a-failed-task)
- [Start a task](/guides/tasks/start-a-task)
