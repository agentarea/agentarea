---
title: Run a command in a sandbox
type: guide
summary: Equip an agent with the shell tool so it can run bash inside its task's sandbox, and read back the output and exit code.
prerequisites:
  - /concepts/sandbox/sessions
  - /concepts/sandbox/why-a-sandbox
related:
  - /guides/sandbox/collect-artifacts-and-logs
  - /reference/limits
  - /guides/tasks/debug-a-failed-task
  - /concepts/sandbox/isolation
last_updated: 2026-07-29
---

# Run a command in a sandbox

Do this when an agent needs to execute code rather than call an API — running a
script, processing a file, invoking a CLI. The agent gets a bash tool whose
commands run inside the sandbox bound to its task.

Do not do this when an HTTP API would answer the question. A tool call to a
remote service is cheaper and does not need a sandbox at all. The shell exists
for work that has to happen on a filesystem.

## Prerequisites

- An agent you can modify, and a configured LLM model
- The MCP manager reachable from the worker, since the shell tool calls its
  sandbox control plane
- Familiarity with [sandbox sessions](/concepts/sandbox/sessions) — the sandbox
  belongs to the task, so files persist between commands within one task

## Steps

### 1. Equip the agent with the shell tool

The shell is a built-in code tool named `agentarea/shell`. Add it when creating
the agent:

```bash
curl -X POST "$AGENTAREA_URL/v1/agents/" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "shell-agent",
    "model_id": "'"$MODEL_ID"'",
    "instruction": "You have a shell tool. Use bash to inspect and process files, then call completion with a short summary.",
    "tools": [{"type": "code", "name": "agentarea/shell"}]
  }'
```

The response carries the agent's `id`. Keep it for the next step.

### 2. Create a task

```bash
curl -X POST "$AGENTAREA_URL/v1/agents/$AGENT_ID/tasks/" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"description": "Create a file called out.txt containing the current date, then show it."}'
```

The task runs asynchronously. Its `id` is what you poll and what scopes the
sandbox.

### 3. Let the agent call bash

You do not invoke the shell yourself — the agent does, through a `bash` tool with
three parameters:

| Parameter | Type | Default | Notes |
|---|---|---|---|
| `command` | string | required | The bash to run. Must be non-empty. |
| `timeout_seconds` | integer | deployment policy | Omit it to use the manager's configured default. Values above the configured maximum are rejected. |
| `artifact_paths` | array of strings | none | Relative paths to copy out durably after the command. |

The command body is capped at 256 KiB.

## Verify

Poll the task until it reaches a terminal state:

```bash
curl -s "$AGENTAREA_URL/v1/agents/$AGENT_ID/tasks/$TASK_ID/status" \
  -H "Authorization: Bearer $TOKEN"
```

Then read the event stream, which contains the tool calls and their results:

```bash
curl -s "$AGENTAREA_URL/v1/agents/$AGENT_ID/tasks/$TASK_ID/events" \
  -H "Authorization: Bearer $TOKEN"
```

A command that ran shows an exit code of `0` alongside its captured stdout. A
non-zero exit code means the command ran and failed, which is different from the
tool failing to run it — the distinction matters when debugging.

To confirm the sandbox itself was allocated, look for a pod labelled with the
task ID:

```bash
kubectl get pods -n agentarea -l mcp.agentarea.io/task-id=$TASK_ID \
  -o custom-columns=NAME:.metadata.name,STATUS:.metadata.labels.mcp\\.agentarea\\.io/status
```

## Troubleshooting

**The agent says it has no shell tool, or never calls bash.** Built-in tools are
disclosed progressively rather than all being present in every prompt, so the
agent may need to activate the tool source before the tool appears. Check the
event stream for an `activate_tool_source` call. If the agent is not activating
it, make the instruction explicit about using the shell tool. Confirm the tool
name is exactly `agentarea/shell` — an unknown name is equipped without error and
simply never resolves.

**The tool returns "shell tool is not configured".** The worker has no MCP
manager URL, so there is no sandbox control plane to call. This is a deployment
problem rather than an agent one: check the worker's MCP manager setting and that
the manager is reachable from the worker.

**A long command reaches its deadline.** The Go manager resolves an omitted
timeout from `SANDBOX_DEFAULT_EXECUTION_TIMEOUT_SECONDS` and rejects values above
`SANDBOX_MAX_EXECUTION_TIMEOUT_SECONDS`; the data-plane provider cannot silently
shorten the persisted command contract. See [limits](/reference/limits).

**Files written by one command are missing in the next.** Within a single task
they should persist, because commands execute in the same pod. If they do not,
the provider session was likely reclaimed between commands — check whether the
task idled past its lease, and see
[debug a failed task](/guides/tasks/debug-a-failed-task).

**`pip install` or `npm install` fails with a read-only or permission error.**
The task does not select an `allowed` or `locked` profile. The operator owns the
single runtime image and filesystem/network policy for the deployment. Inspect
that runtime and its isolation attestation; see
[sandbox isolation](/concepts/sandbox/isolation).

## Related

- [Collect artifacts and logs](/guides/sandbox/collect-artifacts-and-logs) — getting output out
- [Limits](/reference/limits) — the ceilings that apply
- [Sandbox isolation](/concepts/sandbox/isolation) — deployment-owned runtime policy
- [Debug a failed task](/guides/tasks/debug-a-failed-task) — when a command misbehaves
- [Sandbox sessions](/concepts/sandbox/sessions) — why state persists per task
