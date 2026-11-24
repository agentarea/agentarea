---
title: Platform toolsets
type: reference
description: "The agentarea/* toolsets an agent can carry, and the arguments, answer and errors of agentarea/messages, which writes first to a workspace member."
prerequisites:
  - /concepts/agents/what-is-an-agent
related:
  - /concepts/integration/triggers
  - /reference/policy-syntax
  - /guides/agents/deploy-from-a-folder
last_updated: 2026-11-24
---

A platform toolset is a set of AgentArea's own tools an agent carries by its
namespace, in a bundle's `toolsets` list or as a `code` tool of the agent.

## Synopsis

```yaml
# agents/assistant.yaml in a bundle folder
name: assistant
toolsets: [agentarea/messages]
```

A toolset with one method reaches the model under the toolset's name
(`agentarea/messages` is the tool `messages`); one with several as
`<toolset>_<method>`. A policy names the tool by that name, `tool:messages`, or
by the namespace.

| Namespace | Plane | What it does |
|---|---|---|
| `agentarea/agents` | build | Create, list, update, archive, and restore agents in the workspace |
| `agentarea/runs` | operate | Start, monitor, and manage agent execution runs |
| `agentarea/task_definitions` | operate | Save what to ask an agent, and run it on demand or from a trigger |
| `agentarea/skills` | build | Manage workspace skills |
| `agentarea/projects` | build | Manage projects and their skills, agents and MCP instances |
| `agentarea/clients` | federate | Register harnesses as clients and attach toolsets to them |
| `agentarea/members` | govern | List workspace members, invite people, and revoke access |
| `agentarea/policies` | govern | List, inspect, and write the workspace's policy rules |
| `agentarea/triggers` | build | Schedule agents on cron or run them on the events of a stream |
| `agentarea/streams` | build | Create event streams, sources and forwards; read what arrived |
| `agentarea/stream_events` | operate | Read the events a stream recorded after a cursor or since a time |
| `agentarea/inbox` | operate | Inspect runs awaiting human input |
| `agentarea/messages` | operate | Write first to a workspace member through a messenger stream |
| `agentarea/openapi_connections` | build | Manage OpenAPI connections |
| `agentarea/mcp_servers` | build | Start, stop, and manage MCP server instances |
| `agentarea/providers` | build | Manage LLM provider configurations |
| `agentarea/models` | build | Inspect model specifications and model instances |
| `agentarea/secrets` | build | Manage workspace secrets, by name |
| `agentarea/audit` | observe | Inspect workspace audit log entries |
| `agentarea/network` | observe | Inspect the workspace's network topology |
| `agentarea/workspace_config` | build | Export the workspace configuration as YAML |

## agentarea/messages

`send_message` sends a message to a workspace member through the Telegram bot
of a messenger stream, so the agent can start the conversation. Its effect is
`write` and it reaches outside the platform, so a policy can deny it or hold it
for approval like any tool. The message goes only to the Telegram account the
member linked to AgentArea; there is no chat id to give.

### Parameters

| Name | Type | Default | Description |
|---|---|---|---|
| `text` | string | `""` | The message, sent as plain text. Longer than 4096 characters is cut and ends with `(truncated)`. Required unless `files` is given |
| `to` | string | `""` | The member: their user id or email. Empty is the person the run acts for |
| `stream` | string | `""` | A stream name or id. Empty is the only messenger stream the caller may read |
| `files` | string[] | `[]` | Paths of the run's own files, such as `outputs/clip.subtitled.mp4`, sent after the text, each as a message of its own: an mp4 as a video, a JPEG, PNG or WebP up to 10 MB as a photo, anything else as a document. At most 50 MB each |

A messenger stream is one with a source whose type admits Telegram senders;
the first such source of the stream sends.

### Response

| Field | Type | Description |
|---|---|---|
| `sent` | boolean | `true` |
| `to` | string | The member's email, or user id when there is none |
| `stream` | object | `id` and `name` of the stream whose bot sent |
| `messenger` | string | `telegram` |
| `message_id` | integer | Telegram's id of the message; absent when only files were sent |
| `truncated` | boolean | Whether the text was cut |
| `files` | string[] | The files sent, as normalized paths; absent when none |

When the member answers, the update reaches the stream like any message they
send: its session key is their chat, so a trigger with `session.continue`
carries the conversation on.

### Errors

| Error | Meaning | Action |
|---|---|---|
| `<to> is not a member of this workspace` | `to` names nobody in the workspace, or is a chat id | Name a member from `members_list` |
| `<member> has not linked a Telegram account` | The member has no live Telegram link | They write to the stream's bot and open the link it answers with |
| `The workspace has no messenger stream you can write from` | No stream the caller may read has a Telegram source | Add a Telegram source, or grant read on the stream |
| `Several messenger streams reach <member>` | More than one stream qualifies | Pass `stream` |
| `Stream '<name>' has no Telegram source to write from` | `stream` names a stream without one | Name a messenger stream |
| `Telegram refused the message: Forbidden: …` | The member never started the bot, or blocked it | They open the bot in Telegram and press Start |
| `files can be sent only from a run` | `files` was given outside a run | Send files from the run that made them |
| `'<path>' is not a path in the run's workspace` | The path is absolute outside `/workspace/` or climbs out | Pass a path such as `outputs/report.pdf` |
| `<path> cannot be read: …` | The file is not in the run's sandbox, or the sandbox expired | Write it first; check the path |
| `<path> is larger than the 50 MB a Telegram bot sends` | A bot cannot upload it | Compress or split the file |

Every file is read before anything is sent, so a refused path sends nothing.

## Example

```json
{"text": "The weekly CEO report is ready in the workspace files."}
```

```json
{"sent": true, "to": "ceo@example.com", "stream": {"id": "6c1f…", "name": "assistant-bot"},
 "messenger": "telegram", "message_id": 4182, "truncated": false}
```
