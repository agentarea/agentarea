---
title: MCP tool call context
type: reference
description: "The _meta keys, signed X-AgentArea-Context token, progress events and result fields AgentArea uses when it calls a tool on a remote MCP server."
prerequisites:
  - /concepts/integration/mcp
related:
  - /guides/mcp/expose-your-app-tools
  - /guides/mcp/connect-a-remote-server
  - /concepts/execution/events
  - /reference/limits
last_updated: 2026-10-27
---

The conventions AgentArea adds to a standard MCP `tools/call` so a remote MCP
server knows which task, workspace and end user a call is for, and can report
progress. Contract version `1`. Every field is a standard MCP field or a header,
so any MCP client can still call the same server.

The TypeScript server side is `@agentarea/tools`. The platform side is
`agentarea_mcp/tool_context.py` (keys, token) and `MCPServerInstanceService.execute_tool`
(sending them).

## Synopsis

```http
POST /mcp HTTP/1.1
Authorization: Bearer <static credential stored on the instance>
X-AgentArea-Context: <HS256 JWT>
Content-Type: application/json

{"jsonrpc": "2.0", "id": 3, "method": "tools/call",
 "params": {"name": "get_order", "arguments": {"orderId": "A-17"},
  "_meta": {"progressToken": 3,
            "agentarea/protocol": "1",
            "agentarea/task_id": "6f1c…",
            "agentarea/tool_call_id": "call_abc",
            "agentarea/workspace_id": "1b2e…",
            "agentarea/agent_id": "9d4a…",
            "agentarea/end_user_id": "user-42",
            "agentarea/metadata": {"chatId": "c-9"},
            "agentarea/idempotency_key": "6f1c…:call_abc"}}}
```

## When context is sent

| Condition | `_meta` keys and token |
|---|---|
| URL MCP server instance with a `context_secret` set | Sent on every `tools/call` an agent makes |
| URL instance without `context_secret` | Not sent. The call is a plain MCP call |
| Managed instance (`docker`, `command`) whose spec has `"context": {"enabled": true}` | Token sent on every call: an agent's, and a person's or client's (see [Direct callers](#direct-callers)) |
| Other managed instances | Not sent. `context_secret` is refused (422) |
| Bundle | The member instance's own setting applies; `aud` is the member's id |
| `tools/list`, verification | Not sent |

AgentArea never sends `agentarea/*` keys without a token, so a server never has
to trust `_meta` on its own.

## Transport

| | |
|---|---|
| Protocol | MCP over Streamable HTTP, revision `2026-07-28` (2025-era servers are still reached) |
| Connection | A new connection per call; no MCP session is reused |
| Read timeout | 300 s |
| Batching | `tools/call` is never sent in a JSON-RPC batch |
| Static credential | Whatever header the instance stores, e.g. `Authorization: Bearer …` or `X-API-Key: …` |

## `_meta` keys

| Key | Type | Always | Value |
|---|---|---|---|
| `agentarea/protocol` | string | yes | `"1"` |
| `agentarea/task_id` | string | yes | Task the call belongs to |
| `agentarea/tool_call_id` | string | yes | The model's tool call id, unique within the task |
| `agentarea/workspace_id` | string | yes | Workspace that owns the task |
| `agentarea/idempotency_key` | string | yes | `"<task_id>:<tool_call_id>"` |
| `agentarea/agent_id` | string | when known | Agent making the call |
| `agentarea/end_user_id` | string | when set | `end_user_id` given when the task was created |
| `agentarea/metadata` | object | when set | `metadata` given when the task was created |

`progressToken` is also set on every call (the MCP client uses the request id).

## `X-AgentArea-Context` token

| Header | Value |
|---|---|
| `alg` | `HS256` |
| `typ` | `JWT` |

The key is the instance's `context_secret` as UTF-8 bytes.

| Claim | Value |
|---|---|
| `iss` | `agentarea` |
| `aud` | The MCP server instance id (UUID) the token is for |
| `iat`, `exp` | `exp = iat + 300` |
| `jti` | Random UUID per token |
| `tool` | The tool name in `params.name` (the server's own name, not the agent-facing prefixed one) |
| `protocol`, `task_id`, `tool_call_id`, `workspace_id`, `idempotency_key` | Same values as the `_meta` keys |
| `agent_id`, `end_user_id`, `metadata` | Same values as the `_meta` keys, when present |

Every `agentarea/*` key in `_meta` has an equal claim, and the token has no
context claim that `_meta` lacks.

### Direct callers

A person working in an MCP App's view (the `/v1/mcp/{instance_id}/mcp` proxy)
or a client calling a connection (`tools_call`, a registered client's
endpoint) makes a call outside any task. For an instance that takes context,
that call carries the token with these claims instead of the task's, and no
`_meta` keys:

| Claim | Value |
|---|---|
| `protocol`, `workspace_id` | As above |
| `user_id` | The person making the call |
| `user_email` | Their email, when known |
| `client_id` | The client the call came through, when it came through one |
| `tool` | Present only when the request is exactly one `tools/call` |

A server tells the two apart by `task_id`: present on an agent's call, absent
on a direct one.

### Managed instances: the key

A managed instance never has a `context_secret`. Its key is
`hex(HMAC-SHA256(AGENTAREA_MCP_GATEWAY_SECRET, "agentarea/mcp-context/v1:" + instance_id))`,
derived by both the platform and the mcp-manager, which hands it to the
container as `MCP_CONTEXT_KEY` at every start. The spec opts in with
`"context": {"enabled": true}`; any other value is refused when the spec is
saved, and a manager without a gateway secret refuses to start the instance.

### Verification a server performs

1. Check the signature with an `HS256`-only algorithm list, `exp`/`iat` (reject
   tokens older than 10 minutes, allow 30 s skew), `aud` equal to the instance
   id, and `iss` equal to `agentarea`.
2. If `tool` is present, it must equal `params.name`.
3. Every `agentarea/*` key in `_meta` must equal its claim (objects compared
   independently of key order).
4. Run the tool only after all three pass.

Answer a failure on the HTTP layer with a JSON-RPC error and the request `id`:

| Case | HTTP | JSON-RPC `code` |
|---|---|---|
| Missing static credential | 401 | `-32001` |
| Missing token, bad signature, expired, wrong `aud`/`iss` | 401 | `-32001` |
| Valid token that does not match the call, or an unknown major `protocol` | 403 | `-32003` |
| Malformed context value | 400 | `-32602` |
| `tools/call` inside a batch | 400 | `-32600` |

AgentArea reports a 401 or 403 to the agent as
`MCP tool call failed: <host> rejected the credentials (HTTP 401)`.

## Progress

The server sends standard `notifications/progress` on the call's response
stream. The worker relays them as `tool.progress` task events: stored in
`task_events` and put on the task's live stream, so they appear in the task
SSE feed and its history.

```json
{"event_type": "tool.progress",
 "data": {"task_id": "6f1c…", "tool_name": "app__get_order", "tool_call_id": "call_abc",
          "progress": 5, "total": 23, "message": "Reading sheet 5 of 23"}}
```

| Rule | Value |
|---|---|
| Rate | At most one event per 0.5 s per call; notifications in between are dropped |
| Completion | A notification with `progress >= total` is always relayed |
| Values | `progress`, `total`, `message` as the server sent them; `tool_name` is the agent-facing name |
| Heartbeat | Every notification heartbeats the tool activity |
| Part | `tool.progress` derives no part; the tool card stays as `tool.call` / `tool.result` left it |

## Timeout

A call waits for its result for the instance's `tool_timeout_seconds` (in the
instance `json_spec`), progress notifications included, then fails as
`MCP tool call timed out: no result within <n> s` and the server is sent
`notifications/cancelled`.

| Rule | Value |
|---|---|
| Default | 300 s |
| Range | 1 to 1800 s; a value outside it is refused with 422 on create and update |
| Changing it | Takes effect on the next call; a container instance is not restarted |

## Results

| Field | Goes to |
|---|---|
| `content` (text) | The model. Text over 8000 characters is offloaded and the model sees a pointer and a preview |
| `content` (image), or an embedded resource with an `image/*` blob | Stored with the task's offloaded context. A vision model sees the image after the tool result; another model reads `[image <id> not shown …]`. The `tool.result` event carries `images: [{id, mime_type, size}]`, never the bytes. PNG, JPEG, GIF and WebP up to 5 MB, at most 8 per result; the newest 8 of the run go with each model call |
| Embedded text resource | The model, as `[resource <uri>]` followed by its text |
| `structuredContent` | The `tool.result` event as `structured_content`. The model does not read it. Over 16000 characters of JSON it is left out and the event carries `structured_content_dropped: true` |
| `isError: true` | A failed `tool.result`; `content` is the error the model reads |
| `_meta["agentarea/replayed"]: true` | The `tool.result` event as `replayed: true`: the server answered from what it stored for this idempotency key rather than running the tool again |

When `content` is empty, the model reads `structuredContent` as text instead.

## Tool names the model sees

An agent's MCP tool is offered to the model as `mcp__<server>__<tool>`, at most
64 characters (a longer name is cut and ends in an 8-character digest).
`<tool>` is the raw tool name with characters outside `[a-zA-Z0-9_-]` replaced
by `_`. `<server>` comes from the instance name:

| Instance name | `<server>` | Example |
|---|---|---|
| ASCII only | Lowercased, characters outside `[a-zA-Z0-9_-]` replaced by `_` (unchanged from before) | `My GitHub!` → `my_github_` |
| Any other letters | Cyrillic transliterated, accents dropped, runs of anything else collapsed to one `_`, trimmed | `Constractio — инструменты сметчика` → `constractio_instrumenty_smetchika` |
| Nothing readable left (CJK only, say) | `server` | `工具` → `server` |

Two instances with the same `<server>` on one agent are kept apart by a suffix
of the second one's id. Your server receives the raw `<tool>` name in
`tools/call`, never the qualified one, so renaming affects only what the model,
the event stream and policy rules written against `tool:mcp__…` see.

**Compatibility.** Names of instances whose name is ASCII did not change. An
instance with a non-ASCII name was previously offered as `mcp__` followed by one
`_` per non-ASCII character; it now gets the readable label above. Running tasks
keep the names they started with. Rules written as `tool:mcp:<instance id>:<tool>`
(what approval toggles write) are unaffected; a hand-written rule that targeted
the old underscore name must be rewritten to the new name or, better, to
`tool:mcp:<instance id>:<tool>`. Client MCP endpoints apply the same label to a
non-ASCII instance name when the member has no `namespace_prefix`.

## Idempotency

A retried tool activity sends the same `task_id`, `tool_call_id`,
idempotency key and arguments, with a newly minted token. A server that is not
safe to re-run remembers the result per idempotency key and returns it for a
duplicate.
It can say so by setting `_meta["agentarea/replayed"]` to `true` on that result.

A retry's `tool.result` carries `attempt: <n>`. It carries `replayed: true` when
the server said so, when a wallet payment for the call had already settled, or when
the call's cost lines were already in the spend ledger; a replay never writes a
second line. Both fields are absent on a first, fresh call.

## Setting the inputs

| Input | Where | Rules |
|---|---|---|
| `context_secret` | `POST /v1/workspaces/{workspace}/mcp-server-instances/`, `POST …/with-spec` (`instance.context_secret`), `PATCH /v1/workspaces/{workspace}/mcp-server-instances/{instance_id}`, or a bundle's `mcps[].context_secret: "${setup.<key>}"` ([bundles](/concepts/integration/bundles)) | 32 to 512 characters. URL instances only. Write-only: stored in the secret manager as `mcp_instance_{id}_AGENTAREA_CONTEXT_SECRET`; the instance's `json_spec` shows `context_signing: true`. `PATCH` with `null` removes it |
| `metadata` | `POST /v1/workspaces/{workspace}/agents/{agent_id}/tasks/`, `…/tasks/sync`, `…/tasks/schedule` | JSON object, at most 4096 bytes. API key or client-credentials callers only; a browser session gets 403 |
| `end_user_id` | Same endpoints | 1 to 256 characters. Same callers as `metadata` |

The model cannot set `metadata` or `end_user_id`: they are task metadata,
written when the task is created and carried into every tool call of the task,
follow-ups included. Reading the task back (`GET …/tasks/{task_id}`, the task
lists) returns both to API key and service-client callers and `null` to anyone
else. To bill per end user, see
[Charge your users for task cost](/guides/tasks/charge-for-task-cost).

## Versioning

`agentarea/protocol` is `"<major>"` or `"<major>.<minor>"`. Servers reject an
unknown major and accept any minor. Adding an optional key or claim is a minor
change; removing one or changing its meaning is a major change.

## Security notes

- The static credential and `context_secret` are different values. Leaking the
  credential lets an attacker call tools but not assert a workspace, task or
  end user.
- Arguments are not covered by the signature. Within its 5-minute lifetime a
  token can be replayed at the same server for the same tool; idempotency makes
  a replay of the same call a no-op.
- `end_user_id` and `metadata` are assertions by the API caller that created
  the task, relayed by AgentArea. Authorize them against your own data.
- HS256 means the server holding the secret could mint tokens for itself. Use
  one secret per instance.
- Rotation: the platform holds one secret per instance. Make the server accept
  the old and the new secret, `PATCH` the instance with the new one, then drop
  the old one from the server.
