---
title: Start a task
type: guide
summary: Launch an agent run over REST, the CLI, or A2A, and choose the entry point that matches how you need the result delivered.
prerequisites:
  - /concepts/execution/tasks
related:
  - /guides/tasks/stream-events
  - /guides/tasks/attach-files
  - /guides/tasks/cancel-and-retry
  - /concepts/execution/durable-execution
last_updated: 2026-07-29
---

# Start a task

Do this when you want an agent to run once against a prompt you supply. Do not
do this to send a follow-up message into a run that is already going — that is a
command on the existing task, covered in
[Cancel and retry a task](/guides/tasks/cancel-and-retry).

All three entry points create the same task and dispatch the same workflow. They
differ only in how the response reaches you.

## Prerequisites

- An agent that exists and has a model configured. An agent with no `model_id`
  is rejected at creation with 422, not at run time.
- An API key. Create one with `POST /v1/api-keys/` and read `token` from the
  201 response — it is returned once and never again.
- The agent's id. `GET /v1/agents/` lists them.

## Choose an entry point

| Option | Pick it when |
|---|---|
| `POST /v1/agents/{agent_id}/tasks/` | You want to watch the run live. Returns `text/event-stream`, not JSON. |
| `POST /v1/agents/{agent_id}/tasks/sync` | You want a task id back immediately and will poll or stream separately. Returns JSON. |
| CLI | You are at a terminal and want the same thing without writing a request. |
| A2A JSON-RPC | The caller is another agent or an A2A-compatible client. |

`sync` is the misleading name here: it returns a JSON response instead of a
stream. It does **not** wait for the agent to finish. It returns as soon as the
workflow is dispatched, with `status` set to `running`.

## Steps

### Option A — REST, streaming

The response is Server-Sent Events. Do not pipe it to `jq`.

```bash
curl -N -X POST \
  "$AGENTAREA_URL/v1/agents/$AGENT_ID/tasks/" \
  -H "Authorization: Bearer $AGENTAREA_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"description": "Summarise the latest release notes and list breaking changes."}'
```

The stream opens with a `connected` event, then `task_created` carrying the
`task_id`, then the execution events:

```
event: connected
data: {"agent_id": "...", "agent_name": "Release Bot", "message": "Starting task creation", "timestamp": "2026-07-29T10:15:02.114820+00:00"}

event: task_created
data: {"task_id": "3f2a...", "agent_id": "...", "description": "Summarise the latest release notes...", "status": "running", "execution_id": "task-3f2a...", "created_at": "2026-07-29T10:15:02.098431+00:00", "timestamp": "..."}

event: task.started
data: {"event_type": "task.started", "event_id": "...", "timestamp": "...", "data": {...}}
```

### Option B — REST, JSON response

```bash
curl -X POST \
  "$AGENTAREA_URL/v1/agents/$AGENT_ID/tasks/sync" \
  -H "Authorization: Bearer $AGENTAREA_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"description": "Summarise the latest release notes and list breaking changes."}'
```

```json
{
  "id": "3f2a8c11-...",
  "agent_id": "9b1d...",
  "description": "Summarise the latest release notes and list breaking changes.",
  "status": "running",
  "execution_id": "task-3f2a8c11-...",
  "parameters": {},
  "result": null,
  "error": null,
  "failure_reason": null,
  "total_cost": null,
  "created_at": "2026-07-29T10:15:02.098431+00:00"
}
```

Keep `id`. Every other task endpoint needs it alongside the agent id.

### Option C — CLI

```bash
agentarea tasks submit "$AGENT_ID" \
  --data '{"description": "Summarise the latest release notes and list breaking changes."}'
```

Use `agentarea tasks submit-sync` for the JSON form. Loose flags are folded into
the request body, so `--description "..."` works in place of `--data`.

### Option D — A2A JSON-RPC

The endpoint is `POST /v1/agents/{agent_id}/a2a/rpc`. Method names are
PascalCase — `SendMessage`, not `message/send`. A slash-style method returns
"method not found".

```bash
curl -X POST \
  "$AGENTAREA_URL/v1/agents/$AGENT_ID/a2a/rpc" \
  -H "Authorization: Bearer $AGENTAREA_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": "1",
    "method": "SendMessage",
    "params": {
      "message": {
        "role": "USER",
        "parts": [{"text": "Summarise the latest release notes."}]
      }
    }
  }'
```

`SendMessage` returns as soon as the task is submitted. Use
`SendStreamingMessage` for a live SSE stream, or `GetTask` to poll.

### Optional request fields

`TaskCreate` accepts more than `description`:

| Field | Use it to |
|---|---|
| `parameters` | Pass free-form caller or agent-specific input. The legacy `max_iterations` key remains accepted for compatibility, but is converted into persisted governance rather than used as a runtime default. |
| `execution.max_model_turns` | Request a typed model-turn ceiling. Governance may tighten it, never widen it. |
| `requires_human_approval` | Gate the run on an approval before tool calls proceed. |
| `task_policy` | Tighten governance for this run only. It may only narrow the workspace and agent policy, never widen it. |
| `project_id` | Stage a project's files into the task workspace as inputs. |
| `attachments` | Staging refs from an upload. See [Attach files to a task](/guides/tasks/attach-files). |

## Verify

Fetch the task and confirm it has an `execution_id` and a live status:

```bash
curl -s "$AGENTAREA_URL/v1/agents/$AGENT_ID/tasks/$TASK_ID" \
  -H "Authorization: Bearer $AGENTAREA_TOKEN" | jq '{status, execution_id, failure_reason}'
```

```json
{
  "status": "running",
  "execution_id": "task-3f2a8c11-...",
  "failure_reason": null
}
```

`execution_id` present and `status` of `running` means the Temporal workflow
started. A task sitting at `pending` with `execution_id: null` was persisted but
never dispatched.

## Troubleshooting

**The streaming endpoint returns nothing parseable.** `POST
/v1/agents/{agent_id}/tasks/` responds with `text/event-stream`. `curl` without
`-N` buffers it and `jq` cannot parse it. Use `-N`, or switch to `/sync`.

**422 with "does not have a model configured".** The agent was installed from
the catalog without a matching model instance in this workspace, so `model_id`
was left unset. Assign a model to the agent, or pass
`parameters.model_override` on the run.

**422 from the policy layer.** A `task_policy` that widens any limit set at the
workspace or agent scope is rejected — task policy may only tighten. Compare
against `POST /v1/governance/effective-policy/preview` before retrying.

**The task exists but nothing happens and `execution_id` is null.** The workflow
dispatch failed, usually because no Temporal worker is running on the
`agent-tasks` queue. The task row is written before dispatch, so a creation
success does not prove a worker exists. Check the worker, then start a new task
— a task that never dispatched cannot be resumed.

**A creation call returns a task you did not expect.** If `parameters` carries
`channel_origin.chat_id` matching a workflow already running for the same agent,
the message is delivered into that workflow as a follow-up and the existing task
comes back with `status: "routed"`. No new task is created.

## Related

- [Stream task events](/guides/tasks/stream-events)
- [Attach files to a task](/guides/tasks/attach-files)
- [Debug a failed task](/guides/tasks/debug-a-failed-task)
- [Tasks](/concepts/execution/tasks)
