---
title: Platform toolsets
type: reference
description: "The agentarea/* toolsets an agent can carry; the arguments, answer and errors of agentarea/messages, which writes first to a workspace member, and of agentarea/llm, which calls other models as a tool."
prerequisites:
  - /concepts/agents/what-is-an-agent
related:
  - /concepts/integration/triggers
  - /reference/policy-syntax
  - /guides/agents/deploy-from-a-folder
last_updated: 2026-11-26
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
| `agentarea/llm` | runtime | Call another model with a prompt and task files, or ask a decision model |

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
| `files` | string[] | `[]` | Paths of the run's own files, such as `outputs/clip.subtitled.mp4`, sent after the text, each as a message of its own: an mp4 as a video, a JPEG, PNG or WebP up to 10 MB as a photo, anything else as a document. At most 10 files. A file over 50 MB, or one Telegram refuses as too large, is sent as a line `<name> (<size> MB): <link>` to the file in the web app instead |

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
| `linked` | string[] | The files too large to send, sent as links to the task's files in the web app; absent when none |

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
| `<path> is larger than the 50 MB a Telegram bot sends` | A bot cannot upload it and the deployment has no web app URL to link it | Set `AGENTAREA_APP_URL`, or compress or split the file |
| `at most 10 files go in one message` | More than ten paths | Send them in several messages |

Every file is checked before anything is sent, so a refused path or a size the sandbox reports over the limit sends nothing; files are then read and sent one at a time.

## agentarea/llm

`agentarea/llm` lets an agent call another model as a tool: one call, no
tools, the answer returned or written to a file. An agent on a small model
can read drawing sheets with a vision model, choosing per call which one from
its instructions, and keep the long answers out of its own context.

The toolset calls only the models its settings list. Each entry is a model
instance of the workspace, chat or decision, with the reasoning and output
budget a call gets unless it sets its own:

```json
{"type": "code", "name": "agentarea/llm", "settings": {"models": [
  {"model_id": "6f1d…01"},
  {"model_id": "6f1d…02", "reasoning_effort": "high", "max_tokens": 8000}
]}}
```

| Field | Description |
|---|---|
| `model_id` | The model instance. Required; at least one entry, each instance once |
| `reasoning_effort` | A level the model lists. A model that lists none takes no level |
| `reasoning_max_tokens` | A reasoning token budget, for a provider that takes one. Not with `reasoning_effort` |
| `max_tokens` | The most tokens an answer may take |

A decision model takes none of the three. In a bundle the toolset's `models`
names each model as the agent's `model` is; see
[Deploy from a folder](/guides/agents/deploy-from-a-folder).

Every call is held, charged and written to the run's spend ledger as the run's
own model calls are, under the same spend caps, plan entitlements and
per-call token limit.

### llm_call

One call to a chat model.

| Name | Type | Default | Description |
|---|---|---|---|
| `model` | string | | One of the listed models: its instance name, its model's name or its id. Required |
| `prompt` | string | | The user message. Required |
| `system` | string | `null` | A system prompt |
| `files` | string[] | `null` | Paths in the task workspace of images (PNG, JPEG, GIF, WebP) and PDFs, attached as `read_file` attaches them: at most 8 images and 20 PDF pages in all, a PDF at most 10 pages, each within what the model's provider takes |
| `schema` | object | `null` | A JSON Schema the answer must match |
| `output` | string | `null` | A task workspace path to write the answer to |
| `reasoning_effort` | string | `null` | A level the model lists; replaces the entry's level or budget |
| `reasoning_max_tokens` | integer | `null` | A reasoning token budget; replaces the entry's level or budget |
| `max_tokens` | integer | `null` | The most tokens the answer may take; replaces the entry's |

Without a level or budget from the call or the entry the model reasons as it
does by default. The answer's token limit is the smallest of `max_tokens`,
the model's maximum output and the run's per-call limit.

With `schema` the call asks the provider for structured output
(`response_format` of type `json_schema`; `text.format` on the Responses API),
so the model answers by the schema itself. An answer that is still not JSON is
the tool's error; a code fence around the JSON is dropped. Anthropic's own API
takes no response schema: there the call is refused.

### llm_decide

One request to a decision model.

| Name | Type | Default | Description |
|---|---|---|---|
| `model` | string | | One of the listed decision models, named as for `llm_call`. Required |
| `state` | object | | What the questions are about. Required |
| `questions` | object | | The questions by key: `{"type": "choice", "instructions": …, "criteria": {"<option>": "<when>"}}` or `{"type": "score", "instructions": …, "criteria": ["…"]}`. Required |
| `output` | string | `null` | A task workspace path to write the answers to |

### Response

The answer as text: `llm_call`'s reply, or with `schema` its JSON;
`llm_decide`'s answers as a JSON object, one per question. With `output`, the
file it wrote in its place:

```json
{"file_path": "sheets/12.json", "size": 2311}
```

### Errors

| Error | Meaning | Action |
|---|---|---|
| `model '<m>' is not one this agent may call; it may call …` | `model` names no listed model | Name one of those listed |
| `model '<m>' names <n> of the models this agent may call: …` | Two listed models share the name | Give the id |
| `model '<m>' is a decision model; ask it with llm_decide` | The kind does not fit the method | Use the other method |
| `model <name> takes reasoning_effort low, high, not <x>` | A level the model does not list | Pass a listed level |
| `set reasoning_effort or reasoning_max_tokens, not both` | Both in one call | Pass one |
| `this provider takes a reasoning level (reasoning_effort), not a token budget` | The provider refuses a budget | Pass `reasoning_effort` |
| `model <name> does not read images or PDFs` | `files` for a model without vision | Call a vision model |
| `<path> has <n> pages; a PDF attached here has at most 10` | A long PDF | Cut the pages you need into a new PDF in the shell |
| `<path>: … is over the … this model takes` | An image larger than the provider takes | Make a smaller copy in the shell |
| `the model answered text that is not JSON` | The provider ignored the schema; the call is still charged | Call again, or use another model |
| `this provider takes no response schema` | `schema` on a model served by Anthropic's own API | Call without `schema`, or another model |
| `output <path> names a binary file; the answer is text` | `output` ends in `.pdf`, `.png` and the like | Write to `.json`, `.md` or `.txt` |
| A spend cap or billing refusal | The call would pass a cap, or billing refused the hold | As for any model call |

## Example

`agentarea/messages`:

```json
{"text": "The weekly CEO report is ready in the workspace files."}
```

```json
{"sent": true, "to": "ceo@example.com", "stream": {"id": "6c1f…", "name": "assistant-bot"},
 "messenger": "telegram", "message_id": 4182, "truncated": false}
```

`agentarea/llm`, reading a sheet with a vision model:

```json
{"model": "gemini-3.8-flash", "prompt": "List every socket on this sheet.",
 "files": ["sheets/12.png"], "output": "sheets/12.json",
 "schema": {"type": "object", "required": ["sockets"],
            "properties": {"sockets": {"type": "array", "items": {"type": "string"}}}}}
```
