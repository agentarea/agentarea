# Task Assignment Guide

This document explains how to **create**, **assign**, and **query** tasks in AgentArea after the _A2A-compatible_ task-assignment feature was introduced.

The feature is exposed through two complementary APIs:

| Style | Path / Method | Purpose |
|-------|---------------|---------|
| JSON-RPC (A2A protocol) | `tasks/send` **method** | Low-level, schema-driven interface for any AgentArea client. |
| REST convenience | `/v1/tasks/…` | Human friendly wrapper that internally calls the JSON-RPC manager. |

---

## 1. Background – Tasks in the A2A Protocol

A task is a conversation “thread” between a **user** and an **agent**.  
Minimal JSON schema (see `protocols/a2a-schema.json`):

```jsonc
{
  "id": "string",
  "sessionId": "string",
  "status": {
    "state": "submitted | working | …",
    "timestamp": "ISO-8601"
  },
  "history": [ /* Message objects */ ],
  "metadata": { /* arbitrary */ }
}
```

We use the `metadata` object to record:

| Key         | Description                                |
|-------------|--------------------------------------------|
| `user_id`   | Logical owner / requester of the task.     |
| `agent_id`  | Primary agent expected to execute the task |

These keys make it possible to **filter** tasks later.

---

## 2. Sending / Creating a Task

### 2.1 JSON-RPC (low-level)

```jsonc
POST /v1/tasks/send
Content-Type: application/json

{
  "jsonrpc": "2.0",
  "id": "{{$uuid}}",
  "method": "tasks/send",
  "params": {
    "id": "{{$uuid}}",
    "sessionId": "{{$uuid}}",
    "message": {
      "role": "user",
      "parts": [
        { "type": "text", "text": "Hello, please translate this." }
      ]
    },
    "metadata": {
      "user_id": "user-42",
      "agent_id": "agent-99",
      "priority": "high"
    }
  }
}
```

The server responds with a standard `SendTaskResponse` containing the created task.

### 2.2 REST Shortcut

Simpler for scripts / curl:

```bash
curl -X POST http://localhost:8000/v1/tasks/ \
  -H "Content-Type: application/json" \
  -d '{
        "message": "Translate this sentence.",
        "user_id": "user-42",
        "agent_id": "agent-99",
        "metadata": { "priority": "high" }
      }'
```

Response (trimmed):

```json
{
  "id": "8b7d…",
  "session_id": "a1c5…",
  "status": { "state": "submitted", "timestamp": "…" },
  "metadata": { "user_id": "user-42", "agent_id": "agent-99", "priority": "high" }
}
```

---

## 3. Querying Tasks

### 3.1 Get by User

```
GET /v1/tasks/user/{user_id}
```

Example:

```bash
curl http://localhost:8000/v1/tasks/user/user-42
```

Returns:

```json
{
  "tasks": [ { "id": "…", "status": { "state": "submitted" } } ],
  "count": 3
}
```

### 3.2 Get by Agent

```
GET /v1/tasks/agent/{agent_id}
```

```bash
curl http://localhost:8000/v1/tasks/agent/agent-99
```

### 3.3 Get a Single Task

```
GET /v1/tasks/{task_id}
```

---

## 4. Python Example

The repository contains `examples/task_assignment_examples.py` which demonstrates end-to-end usage:

```python
from examples.task_assignment_examples import run_examples
run_examples()
```

The script:

1. Creates three tasks (user-only, agent-only, combined).
2. Queries tasks by user and agent.
3. Fetches an individual task.

---

## 5. Implementation Notes

* **In-memory storage** – `InMemoryTaskManager` keeps tasks in a dict.  
  Restarting the service clears the store. Future adapters (SQL, Redis, etc.) will plug into `BaseTaskManager`.
* **Filtering logic** lives in:
  * `BaseTaskManager.on_get_tasks_by_user/agent`
  * `InMemoryTaskManager` concrete implementation.
* **Metadata is required** for correct filtering. If you omit `user_id` or `agent_id`, the task will not appear in the respective query endpoint.
* **Event Streaming & Push Notifications** continue to work the same way (`tasks/sendSubscribe`, SSE, etc.).

---

## 6. Troubleshooting

| Issue | Resolution |
|-------|------------|
| Endpoint returns empty list | Verify that the task’s `metadata` contains the expected `user_id` or `agent_id`. |
| `404 Task not found` | Check you are querying the correct `task_id`. |
| `500 Internal Server Error` | Inspect server logs; common cause is malformed JSON in request. |

---

## 7. Further Reading

* `protocols/a2a-schema.json` – Full JSON schema definition.
* `core/agentarea/modules/tasks/in_memory_task_manager.py` – Reference implementation.
* `docs/architecture/event_system_extensibility.md` – How events are propagated.

---

_Enjoy automating your workflows with AgentArea!_
