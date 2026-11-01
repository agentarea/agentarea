---
title: Policy rule syntax
type: reference
description: "Every field, effect, subject type and target form of a governance policy rule, and which combinations compile into an enforced policy."
prerequisites:
  - /concepts/governance/policy-engine
related:
  - /reference/authorization-model
  - /reference/limits
  - /guides/governance/authorize-a-tool-call
  - /guides/governance/set-a-budget
last_updated: 2026-10-20
---

One `PolicyRule` row expresses one governance intent for one subject. Rules are
managed under `/v1/workspaces/{workspace}/policies`; see the generated API reference for request and
response shapes.

## Synopsis

```json
{
  "subject_type": "workspace",
  "subject_id": "1c2f0a9b-4d6e-4b71-9f30-8a5c7d1e2b44",
  "target": "tool:send_email",
  "effect": "deny",
  "params": {},
  "condition": null,
  "enabled": true,
  "priority": 0
}
```

Rules of one subject layer compile into a `PolicyDocument`. The layers resolve in
the order `workspace → agent → user → task` into one immutable `EffectivePolicy`
carrying `source_policy_ids` and `resolver_version` (`policy-resolver-v1`).

## Fields

| Name | Type | Default | Description |
|---|---|---|---|
| `id` | string (UUID) | server-assigned | Read-only. Empty string in a response when unset. |
| `subject_type` | enum | required | Which kind of subject the rule binds to. See [Values](#values). |
| `subject_id` | string | required | Workspace id, agent UUID, or user id, matching `subject_type`. |
| `target` | string | required | Selector for what the rule applies to. See [Values](#values). |
| `effect` | enum | required | What the rule does. See [Values](#values). |
| `params` | object | `{}` | Effect-specific values. See [Params by effect](#params-by-effect). |
| `condition` | string \| null | `null` | Accepted, stored, returned. **Never evaluated.** See [Enforcement](#enforcement). |
| `enabled` | boolean | `true` | Disabled rules are skipped when the layer compiles. |
| `priority` | integer | `0` | Stored and returned. Not used by the compiler or the resolver. |

`PATCH` replaces `params` wholesale rather than merging keys.

## Values

### Subject types

| Value | `subject_id` holds | Resolved into a snapshot |
|---|---|---|
| `workspace` | workspace id | Yes — first layer |
| `agent` | agent UUID | Yes — second layer |
| `user` | user id of the task creator | Yes — third layer |
| `group` | group id | **No.** Never read by the resolver. |

The task layer is not a rule. It is supplied as a `PolicyDocument` in
`task_policy` at task creation.

### Effects

| Value | Meaning |
|---|---|
| `allow` | Add the target to the layer's tool allowlist, or, on a `registry` or `registry_trust` target, to its install allowlist. |
| `deny` | Add the target to the layer's tool denylist, or, on a `registry` or `registry_trust` target, refuse installs from it. |
| `cap` | Set a numeric ceiling. |
| `approval` | Require human sign-off. |
| `safety` | Toggle a content-safety filter. |
| `egress` | Declare a container egress allowlist. Never compiles into the runtime document. |

### Target selectors

`target` parses as `kind` or `kind:value`. `*` parses as kind `all` with no
value. A selector naming an unknown kind, or with an empty component, is rejected
at parse time.

| Kind | Form | Accepted by the parser | Reaches the runtime policy |
|---|---|---|---|
| `tool` | `tool:<name>` | Yes | Yes, with `allow`, `deny` or `approval` |
| `tool` | `tool:*` | Yes | Only with `approval` |
| `all` | `*` | Yes | Only with `approval` |
| `spend` | `spend` | Yes | Only with `cap` |
| `service` | `service` | Yes | Only with `cap` |
| `tokens` | `tokens` | Yes | Only with `cap` |
| `content` | `content` | Yes | Only with `safety` |
| `mcp` | `mcp:<id>` | Yes | Only with `egress`, which core does not enforce |
| `model` | `model:<id>` | Yes | **No** |
| `skill` | `skill:<id>` | Yes | **No** |
| `collection` | `collection:<id>` | Yes | **No** |
| `registry` | `registry:<registry id>` or `registry:github` | Yes, with `allow` or `deny` on a `workspace` or `user` subject only | **No.** Decided on catalog install; see [Install rules](#install-rules) |
| `registry_trust` | `registry_trust:<level>`, level one of `official`, `verified`, `community`, `private` | Yes, with `allow` or `deny` on a `workspace` or `user` subject only | **No.** Decided on catalog install |

Tool names are matched with `fnmatch` glob semantics against the LLM-facing tool
name and the tool's other names below.

A tool that comes from a connection is allowed only by its connection's id.
Every other name it has only denies it or holds it for approval: an `allow`
naming one of those does not admit it, and in a workspace with any `allow` on
tools the tool is then denied.

| Tool | Names an `allow` matches | Names that only `deny` or require `approval` |
|---|---|---|
| MCP | `mcp:<instance id>:<tool>` | The LLM-facing `mcp__<server>__<tool>`, `mcp:<instance name>:<tool>`, the raw `<tool>` the server advertises |
| OpenAPI operation | `openapi:<connection id>:<tool>` | The LLM-facing operation name, the spec's `operationId`, the connection's name and its id alone |
| Delegate to a workspace agent | `agent:<agent id>` | The LLM-facing `delegate_to_<name>` and the delegate's name |
| Delegate to a remote agent | `a2a:<agent address>` | The LLM-facing `delegate_to_<name>` and the delegate's name |
| Built-in or platform tool | The LLM-facing name | Its config name (a code toolset's namespace) |

Connection names are not unique, and any workspace member can add a connection
and choose its name, its server's tool names and its OpenAPI `operationId`s. An
`allow` that matched those names would admit every connection that reused them.
To allow a connection tool, name it as `tool:mcp:<instance id>:<tool>` or
`tool:openapi:<connection id>:<tool>`; the connection's page shows the id.
A delegate's tool name comes from an agent name, which any member chooses and
which is not unique either, so a delegate is allowed as
`tool:agent:<agent id>`, or a remote one as `tool:a2a:<agent address>`.

### Params by effect

| Effect | Target | Key | Type | Notes |
|---|---|---|---|---|
| `cap` | `spend` | `amount_usd` | string \| number | Required. Omitted means the rule is skipped. |
| `cap` | `spend` | `period` | `"month"` \| `"run"` | Any other value skips the rule. Defaults to `"month"` when absent. |
| `cap` | `spend` | `category` | `"llm"` \| `"tools"` | Optional. Counts only model calls (`llm`) or only tool calls (`tools`). Absent: all spend. See [Spend caps by kind](#spend-caps-by-kind). |
| `cap` | `spend` | `client_id` | string | Optional. Counts only this Registered Client's lines. Monthly only. Not with `category: llm`. |
| `cap` | `spend` | `connection_id` | string | Optional. Counts only this connection's tool lines. Not with `category: llm`. See [tool costs](/reference/tool-costs). |
| `cap` | `spend` | `tool` | string | Optional, with `connection_id`. Counts only this tool of the connection. A scoped cap bound to an agent also counts only that agent's lines; every scoped cap that matches a call applies. |
| `cap` | `spend` | `currency` | ISO 4217 code | Optional. The cap's currency; `amount_usd` is in it, and the cap counts only lines in it. Default: the billing currency. Monthly only. Nothing is converted. |
| `cap` | `service` | `amount_usd` | string \| number | Required. Caps the run's wallet payments (x402, MPP) in USD. For all tool spend use `cap` on `spend` with `category: tools`. |
| `cap` | `tokens` | `max_tokens` | integer | Optional. |
| `cap` | `tokens` | `max_tokens_per_call` | integer | Optional in an individual rule, but required in the resolved runtime contract and enforced on every LLM call. |
| `approval` | `*`, `tool:*` | `approvers` | array of subject refs | Optional. Empty means any caller may approve. |
| `approval` | `tool:<name>` | `approvers` | array of subject refs | Optional. Stored under `approvers_by_tool[<name>]`. |
| `safety` | `content` | `prompt_injection` | boolean | Coerced with `bool()`. |
| `safety` | `content` | `output_sanitizer` | boolean | Coerced with `bool()`. |
| `safety` | `content` | `answer_check` | object | `{enabled?: bool = true, language?: string, rewrite_instruction?: string (≤4000)}`; unknown keys are refused. See [Answer check](#answer-check). |
| `egress` | `mcp:<id>` | `allowed_hosts` | array of strings | A non-list value skips the rule. |

### Spend caps by kind

A `cap` on `spend` takes one `period` and at most one `category`, and binds to the
workspace (every agent's spend), an agent (its own) or, with `client_id`, a Registered
Client. Every cap that matches applies.

| Counts | `period: month` | `period: run` |
|---|---|---|
| All spend | `{}` | `{}`, the run budget |
| LLM spend | `{category: llm}` | `{category: llm}` |
| Tool spend | `{category: tools}` | `{category: tools}` |
| One connection or tool | `{connection_id, tool?}` | `{connection_id, tool?}` |
| One client | `{client_id}` | — |

| Cap | Checked | What stops |
|---|---|---|
| All spend, month | When a run is submitted or starts, and before every tool call | The run, or the call |
| All spend, run | Before every model turn and every tool call | The run; in a chat it waits for a continuation grant |
| LLM spend, month | When a run is submitted, starts or resumes | The run; tool calls by Registered Clients still go through |
| LLM spend, run | Before every model turn | The run, with `failure_reason` `llm_run_cap_exceeded`; no continuation |
| Tool spend, connection or tool, month | Before every tool call, over the month's lines | The call; the model is told why and the run goes on |
| Tool spend, connection or tool, run | Before every tool call, over the run's lines | The call; the run goes on |

A run's tool spend is the sum of its own task's ledger lines, across resumed runs;
a delegated agent's calls count against its own task. A cap is reached once its sum
equals it, and the call or turn that crosses it is not undone.

Approver references are `user:<id>`, `group:<id>`, or a userset
`<type>:<id>#<relation>`. A bare id is rejected at write time. Only `user:<id>`
grants approval at resolution.

### Merge and validation rules

Applied per layer in order. A lower layer may only tighten.

| Dimension | Merge | Rejected when a lower layer |
|---|---|---|
| `budget.*` | minimum | exceeds a higher ceiling |
| `tokens.*` | minimum | exceeds a higher ceiling |
| `tools.denied` | union | — |
| `tools.allowed` | lower replaces higher when present | adds a pattern outside every higher pattern |
| `approval.requires_human_approval` | logical OR | sets `false` where a higher layer set `true` |
| `approval.escalation_rules` | union | — |
| `approval.approvers` | union | — |
| `approval.approvers_by_tool` | union per tool key | — |
| `content_safety.prompt_injection_detection_enabled`, `content_safety.output_sanitizer_enabled` | logical OR | sets `false` where a higher layer set `true` |
| `content_safety.answer_check` | the lowest layer that sets it wins (an agent's over the workspace's); any rule that sets it overrides the agent's own setting | — |

A rejected chain raises a validation error, surfaced as HTTP 422.

## Answer check

`answer_check` looks at an agent's final answer before the person sees it. It
has two sources, and exactly one of them decides for a run:

1. A `safety` rule on `content` that sets `answer_check`, at any scope. It is an
   override, set by whoever can manage policies: `{enabled: false}` turns the
   check off for an agent whose own setting has it on, and a rule that turns it
   on replaces the agent's language and instruction with its own.
2. Otherwise the agent's own `answer_check` setting (`PATCH /v1/agents/{id}`
   with `{"answer_check": {"language": "ru"}}`, or the agent's edit form).
   Anyone who can edit the agent can set it; `null` leaves the check off.

Both take the same object, `{enabled?: bool = true, language?: string,
rewrite_instruction?: string (≤4000)}`. A rule on the agent:

```json
{"subject_type": "agent", "subject_id": "<agent id>", "target": "content",
 "effect": "safety", "params": {"answer_check": {"language": "ru"}}}
```

In a bundle, the same rule is a policy whose `subject` is the agent's key:

```yaml
policies:
  - key: clean_answers
    subject: smetchik
    target: content
    effect: safety
    params: {answer_check: {language: ru}}
```

| Leak | Found when the answer, outside links, file names and code blocks, has |
|---|---|
| `cjk` | Chinese, Japanese or Korean characters. Off for `language` `zh`, `ja`, `ko` |
| `tool_name` | The name of one of the agent's tools, or an MCP tool's raw name |
| `identifier` | A `snake_case` code (when no tool name was found) |
| `stack_trace` | `Error: `, `TypeError` and kin, `ENOENT`, `at f (/path`, `node_modules/`, a Python traceback |
| `json` | A JSON object (`{"key":`) |
| `english` | `language: ru` only, in a mostly Cyrillic answer: a lowercase Latin word of four or more letters other than `xlsx`, `docx`, `html`, `http`, `https`, `mailto` |

With no leak nothing happens. Otherwise the workflow makes **one** extra call to
the agent's own model, with no tools and no streaming, asking it to fix only
the leaks found (`rewrite_instruction` replaces the default instruction; the
reply format below is appended to either). The model answers in two blocks,
`<changes>` (what it fixed) and `<answer>` (the corrected answer). Only the
`<answer>` block reaches the person, and only when there is exactly one, it is
not empty and it keeps every link of the original; otherwise the original
stays, minus CJK characters if those were the leak.

While the check is on, the reply text is withheld from the live stream: the
run's `llm.call.chunk` events carry `thinking` but an empty `chunk`, so a client
shows the call in progress. A text-only reply is the final answer, and it is
checked before its `llm.call.completed` is published, so that event already
carries the checked text. An answer given through the `completion` tool is
checked when the run completes.

| What a client sees | |
|---|---|
| `llm.call.completed` of the turn | `content` = the checked answer |
| `llm.call.completed` with `purpose: "answer_check"` | The rewrite call: its cost and usage, and `content` = the checked answer. Same `execution_id`/`iteration` as the turn, so it supersedes the same reply part |
| `answer.checked` | `{iteration, leaks: [{kind, sample}], rewritten, changes}`: what was found and the model's `<changes>`, for audit; never shown as the answer |
| `task.completed` `result`, the task's `result.response` | The checked answer |

The rewrite is metered like any model call and counts against the run's budget.

## Enforcement

A rule that parses is not necessarily a rule that acts. The compiler skips
unrecognised effect and target combinations at debug log level, so the row exists
and the API returns it while the runtime never sees it.

| Surface | Status |
|---|---|
| `cap` on `spend` / `service` / `tokens` | Enforced. See [Spend caps by kind](#spend-caps-by-kind) |
| `deny` on `tool:<name>` | Enforced |
| `allow` on `tool:<name>` | Enforced |
| `approval` on `*`, `tool:*`, `tool:<name>` | Enforced in the agent workflow only |
| `safety` on `content` | `prompt_injection` and `output_sanitizer` by the two registered content filters; `answer_check` by the agent workflow on its final answer |
| `condition` on any rule | **Inert.** No resolver, compiler or gate reads it. |
| `subject_type: group` | **Inert.** The resolver reads workspace, agent and user layers only. |
| `priority` | **Inert.** Stored and returned; not used in ordering. |
| `deny` / `allow` on `tool:*` | **Inert.** Skipped as a wildcard. |
| `deny` / `allow` on `mcp:` / `model:` / `skill:` / `collection:` | **Inert.** |
| `cap` on any target other than `spend` / `service` / `tokens` | **Inert.** |
| `approval` on any target other than `*` / `tool:*` / `tool:<name>` | **Inert.** |
| `safety` on any target other than `content` | **Inert.** |
| `allow` / `deny` on `registry:` / `registry_trust:` | Enforced by the catalog install check, not by the runtime policy. See [Install rules](#install-rules) |
| `egress` on `mcp:<id>` | **Inert in core.** Stored and readable; core enforces no container network boundary and the reader helper has no caller in this repository. |
| `tokens.max_tokens_per_call` | **Inert.** Resolved and merged; never written into guard state. |

Two further enforcement boundaries:

| Boundary | Behaviour |
|---|---|
| Snapshot timing | Resolved once at task creation. A rule changed afterwards does not reach a running task. |
| MCP proxy requests | Resolve the workspace and calling user layers only. Agent-scoped and task rules do not apply. |

## Install rules

Rules on `registry:` and `registry_trust:` decide whether a catalog item may
become a workspace's own. The check reads the enabled rules of the workspace
and of the acting user, each as its own layer:

| Situation in a layer | Decision |
|---|---|
| A `deny` names the item's registry or its trust level | Refused |
| The layer has any `allow` on these targets and none names the registry or its trust level | Refused |
| Otherwise | Allowed |

A lower layer cannot widen a higher one's allowlist: every layer must allow.
`registry:github` is a skill imported straight from a GitHub URL, with trust
`community`. The check runs on catalog install, on attaching a catalog skill to
an agent, on editing a catalog item, on updating an installed skill, on a
GitHub URL import, and when a task uses a catalog skill or agent the workspace
never installed. A refusal answers `403` through the API and fails a task as
non-retryable. Skills installed before a rule are not re-checked.

## Defaults and overrides

New workspaces are seeded from `config/default_policies.yaml`. Seeding is
idempotent per `(target, effect, period)` dimension: a dimension the workspace
already has is left untouched.

| Target | Effect | Params |
|---|---|---|
| `spend` | `cap` | `amount_usd: "500.00"`, `period: month` |
| `spend` | `cap` | `amount_usd: "50.00"`, `period: run` |
| `tokens` | `cap` | `max_tokens: 20000000`, `max_tokens_per_call: 100000` |
| `content` | `safety` | `prompt_injection: true`, `output_sanitizer: true` |

No approval rule is seeded.

| Override | Effect |
|---|---|
| `GOVERNANCE_DEFAULT_POLICIES_PATH` | Path to an alternative defaults file. Unset uses the packaged `config/default_policies.yaml`. |
| File absent | New workspaces start with no rules; logged at info level, not an error. |

## Example

Deny one tool for one agent, and require approval on another with a named
approver:

```json
[
  {
    "subject_type": "agent",
    "subject_id": "3f9c1e42-7b5a-4f3e-9a10-2c8d6b4e1f77",
    "target": "tool:send_email",
    "effect": "deny"
  },
  {
    "subject_type": "agent",
    "subject_id": "3f9c1e42-7b5a-4f3e-9a10-2c8d6b4e1f77",
    "target": "tool:refund_payment",
    "effect": "approval",
    "params": {"approvers": ["user:alice@example.com"]}
  }
]
```

Resolved:

```json
{
  "tools": {"allowed": null, "denied": ["send_email"]},
  "approval": {
    "requires_human_approval": null,
    "escalation_rules": ["refund_payment"],
    "approvers": [],
    "approvers_by_tool": {"refund_payment": ["user:alice@example.com"]}
  },
  "resolver_version": "policy-resolver-v1"
}
```

## Related

<Columns cols={2}>
  <Card title="Authorization model" icon="book" href="/reference/authorization-model">
    The separate resource authorization surface
  </Card>
  <Card title="Limits" icon="book" href="/reference/limits">
    The numeric ceilings and their code defaults
  </Card>
  <Card title="Errors" icon="book" href="/reference/errors">
    The validation and permission responses these rules produce
  </Card>
  <Card title="The policy engine" icon="scale-balanced" href="/concepts/governance/policy-engine">
    How the layers merge
  </Card>
</Columns>
