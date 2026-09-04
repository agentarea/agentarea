---
title: Retrieve task artifacts
type: guide
summary: List the files a task produced and download them through the API, with integrity verified before any bytes are returned.
prerequisites:
  - /concepts/execution/artifacts
related:
  - /guides/tasks/attach-files
  - /guides/tasks/debug-a-failed-task
  - /concepts/execution/tasks
last_updated: 2026-07-29
---

# Retrieve task artifacts

Do this when an agent produced a file you need — a report, a chart, a
transformed dataset. Do not use this to browse workspace or project storage;
these endpoints serve one task's workspace and nothing else.

Artifacts survive the sandbox that produced them. They are committed to durable
storage before the tool call that created them returns, so a file listed here is
a file that exists.

## Prerequisites

- A task id and its agent id.
- An API key for the workspace that owns the task. A task in another workspace
  returns 404, not 403.

## Steps

### 1. List what the task produced

```bash
curl -s "$AGENTAREA_URL/v1/agents/$AGENT_ID/tasks/$TASK_ID/artifacts" \
  -H "Authorization: Bearer $AGENTAREA_TOKEN" | jq
```

```json
[
  {
    "path": "tasks/3f2a8c11-.../workspace/inputs/attachments/report.csv",
    "size": 20481,
    "content_type": "text/csv",
    "last_modified": null,
    "download_url": "/v1/agents/9b1d.../tasks/3f2a8c11-.../artifacts/files/tasks/3f2a8c11-.../workspace/inputs/attachments/report.csv"
  },
  {
    "path": "tasks/3f2a8c11-.../workspace/out/summary.md",
    "size": 1284,
    "content_type": "text/markdown",
    "last_modified": null,
    "download_url": "/v1/agents/9b1d.../tasks/3f2a8c11-.../artifacts/files/tasks/3f2a8c11-.../workspace/out/summary.md"
  }
]
```

`path` is always `tasks/{task_id}/workspace/{relative_path}`. `download_url` is
an AgentArea API path, not an object-store URL — it is relative, so prefix it
with your API base.

Inputs you attached and outputs the agent wrote both appear here. Tell them
apart by prefix: attachments land under `inputs/attachments/`.

### 2. Download one file

```bash
ARTIFACT="tasks/$TASK_ID/workspace/out/summary.md"
curl -s -o summary.md \
  "$AGENTAREA_URL/v1/agents/$AGENT_ID/tasks/$TASK_ID/artifacts/files/$ARTIFACT" \
  -H "Authorization: Bearer $AGENTAREA_TOKEN"
```

The response streams with `Content-Length` and a `Content-Disposition` filename.
The body is verified against the stored SHA-256 before the first byte is sent,
so a partial or corrupted object fails the request instead of writing a bad file.

Or follow the `download_url` from the listing directly:

```bash
URL=$(curl -s "$AGENTAREA_URL/v1/agents/$AGENT_ID/tasks/$TASK_ID/artifacts" \
  -H "Authorization: Bearer $AGENTAREA_TOKEN" \
  | jq -r '.[] | select(.path | endswith("summary.md")) | .download_url')
curl -s -O -J "$AGENTAREA_URL$URL" -H "Authorization: Bearer $AGENTAREA_TOKEN"
```

### 3. Download everything

There is no archive endpoint. Loop the listing:

```bash
curl -s "$AGENTAREA_URL/v1/agents/$AGENT_ID/tasks/$TASK_ID/artifacts" \
  -H "Authorization: Bearer $AGENTAREA_TOKEN" \
  | jq -r '.[].download_url' \
  | while read -r url; do
      curl -s -O -J "$AGENTAREA_URL$url" -H "Authorization: Bearer $AGENTAREA_TOKEN"
    done
```

## Verify

Confirm the downloaded bytes match what the task committed. The listing's `size`
is the manifest's recorded size:

```bash
curl -s "$AGENTAREA_URL/v1/agents/$AGENT_ID/tasks/$TASK_ID/artifacts" \
  -H "Authorization: Bearer $AGENTAREA_TOKEN" \
  | jq -r '.[] | select(.path | endswith("summary.md")) | .size'
wc -c < summary.md
```

```
1284
1284
```

Equal sizes plus a 200 response means the digest check passed on the server —
the endpoint does not return a body it could not verify.

## Troubleshooting

**The listing is empty on a completed task.** The agent answered from context
without writing files. Only files committed to the task workspace appear here;
text in the final response is not an artifact. Read `final_response` from
`GET /v1/agents/{agent_id}/tasks/{task_id}/summary` instead.

**404 on a path that appears in the listing.** The `artifact_path` segment must
be the full `tasks/{task_id}/workspace/...` value, repeated after
`/artifacts/files/`. Passing only the relative tail (`out/summary.md`) 404s,
because the endpoint validates that the first two segments match the task.
Copy `download_url` rather than assembling the path.

**404 on anything outside `workspace/`.** Only the `tasks/{task_id}/workspace/`
subtree is downloadable through this endpoint. Other prefixes under the task
return 404 by design.

**The agent said it wrote a file but nothing is listed.** Copy-out happens when
the shell tool returns, and it refuses files over 16 MiB per artifact or beyond
the 1 GiB per-task durable budget. A refused copy is reported as an error on
that tool result, so check the `tool.result` events for the call that created
it — see [Debug a failed task](/guides/tasks/debug-a-failed-task).

**A large download is slow to start.** Verification reads and hashes the whole
object before yielding the first byte, spooling to disk past 8 MiB. Time to
first byte scales with file size; this is the integrity guarantee, not a stall.

**The `expires_in` query parameter appears to do nothing.** It does nothing. It
is accepted for backwards compatibility; these links are API routes behind
normal authorization and do not expire.

## Related

- [Attach files to a task](/guides/tasks/attach-files)
- [Artifacts](/concepts/execution/artifacts)
- [Debug a failed task](/guides/tasks/debug-a-failed-task)
