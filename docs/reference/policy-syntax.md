---
title: Policy rule syntax
type: reference
summary: Every field, effect, subject type and target form of a governance policy rule, and which combinations compile into an enforced policy.
prerequisites:
  - /concepts/governance/policy-engine
related:
  - /reference/authorization-model
  - /reference/limits
  - /guides/governance/authorize-a-tool-call
  - /guides/governance/set-a-budget
last_updated: 2026-07-29
---

# Policy rule syntax

One `PolicyRule` row expresses one governance intent for one subject. Rules are
managed under `/v1/policies`; see the generated API reference for request and
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
| `allow` | Add the target to the layer's tool allowlist. |
| `deny` | Add the target to the layer's tool denylist. |
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

Tool names are matched with `fnmatch` glob semantics against the LLM-facing tool
name.

### Params by effect

| Effect | Target | Key | Type | Notes |
|---|---|---|---|---|
| `cap` | `spend` | `amount_usd` | string \| number | Required. Omitted means the rule is skipped. |
| `cap` | `spend` | `period` | `"month"` \| `"run"` | Any other value skips the rule. Defaults to `"month"` when absent. |
| `cap` | `service` | `amount_usd` | string \| number | Required. |
| `cap` | `tokens` | `max_tokens` | integer | Optional. |
| `cap` | `tokens` | `max_tokens_per_call` | integer | Optional in an individual rule, but required in the resolved runtime contract and enforced on every LLM call. |
| `approval` | `*`, `tool:*` | `approvers` | array of subject refs | Optional. Empty means any caller may approve. |
| `approval` | `tool:<name>` | `approvers` | array of subject refs | Optional. Stored under `approvers_by_tool[<name>]`. |
| `safety` | `content` | `prompt_injection` | boolean | Coerced with `bool()`. |
| `safety` | `content` | `output_sanitizer` | boolean | Coerced with `bool()`. |
| `egress` | `mcp:<id>` | `allowed_hosts` | array of strings | A non-list value skips the rule. |

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
| `content_safety.*` | logical OR | sets `false` where a higher layer set `true` |

A rejected chain raises a validation error, surfaced as HTTP 422.

## Enforcement

A rule that parses is not necessarily a rule that acts. The compiler skips
unrecognised effect and target combinations at debug log level, so the row exists
and the API returns it while the runtime never sees it.

| Surface | Status |
|---|---|
| `cap` on `spend` / `service` / `tokens` | Enforced |
| `deny` on `tool:<name>` | Enforced |
| `allow` on `tool:<name>` | Enforced |
| `approval` on `*`, `tool:*`, `tool:<name>` | Enforced in the agent workflow only |
| `safety` on `content` | Enforced by the two registered content filters |
| `condition` on any rule | **Inert.** No resolver, compiler or gate reads it. |
| `subject_type: group` | **Inert.** The resolver reads workspace, agent and user layers only. |
| `priority` | **Inert.** Stored and returned; not used in ordering. |
| `deny` / `allow` on `tool:*` | **Inert.** Skipped as a wildcard. |
| `deny` / `allow` on `mcp:` / `model:` / `skill:` / `collection:` | **Inert.** |
| `cap` on any target other than `spend` / `service` / `tokens` | **Inert.** |
| `approval` on any target other than `*` / `tool:*` / `tool:<name>` | **Inert.** |
| `safety` on any target other than `content` | **Inert.** |
| `egress` on `mcp:<id>` | **Inert in core.** Stored and readable; core enforces no container network boundary and the reader helper has no caller in this repository. |
| `tokens.max_tokens_per_call` | **Inert.** Resolved and merged; never written into guard state. |

Two further enforcement boundaries:

| Boundary | Behaviour |
|---|---|
| Snapshot timing | Resolved once at task creation. A rule changed afterwards does not reach a running task. |
| MCP proxy requests | Resolve the workspace and calling user layers only. Agent-scoped and task rules do not apply. |

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

## See also

- [Authorization model](/reference/authorization-model) — the separate resource
  authorization surface.
- [Limits](/reference/limits) — the numeric ceilings and their code defaults.
- [Errors](/reference/errors) — the validation and permission responses these
  rules produce.
- [The policy engine](/concepts/governance/policy-engine) — how the layers merge.
