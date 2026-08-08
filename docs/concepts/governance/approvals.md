---
title: Approvals
type: concept
summary: How a tool call pauses for a human, who is allowed to resolve it, and which execution paths have no approval flow at all.
prerequisites:
  - /concepts/governance/policy-engine
  - /concepts/governance/tool-authorization
related:
  - /concepts/governance/tool-authorization
  - /concepts/governance/policy-engine
  - /concepts/governance/audit
last_updated: 2026-07-29
---

# Approvals

An approval turns a tool call into a question. The workflow stops before the call
runs, records who may answer, waits, and resumes only when a designated approver
signals a decision. Because the wait happens inside a durable Temporal workflow,
it survives worker restarts and can last as long as it needs to.

Approval is a dimension of the effective policy, not a flag on a tool. The agent
editor's per-tool "requires approval" checkbox looks like a flag, but it is a
view onto a policy rule — the API translates it into one and reads it back. A
task cannot switch approval off for itself, and the requirement only ever
tightens as it moves down the scopes.

## The problem

Some actions should not be taken by a model unsupervised — refunding a payment,
deleting a record, sending mail to a customer. Two naive designs both fail.

Blocking them outright is not the answer: the agent then cannot do the job it was
built for, and someone will remove the restriction rather than lose the workflow.

Putting the pause at the execution boundary does not work either. A tool call runs
inside a Temporal activity, and an activity has a timeout and cannot wait for a
human. An interceptor at that boundary can only fail the call — which reads as an
error, not a pending decision, and loses the model's context in the process. The
pause has to happen where the durable state lives.

## How AgentArea approaches it

### Writing the rule

Approval is expressed as a policy rule with effect `approval`, and the target
decides its shape:

- **`*` or `tool:*`** — global. Sets `requires_human_approval: true`; every
  capability tool call pauses. Approvers from `params.approvers` apply to all of
  them.
- **`tool:<name>`** — per tool. Adds the name to `escalation_rules`, and stores
  `params.approvers` under `approvers_by_tool[<name>]` so distinct tools keep
  distinct signoff lists rather than pooling into one.

Approvers are written as subject references — `user:<id>`, `group:<id>`, or a
userset `<type>:<id>#<relation>` — and are validated at write time. A bare id is
rejected so the data stays relationship-native.

Most approval rules are not written by hand. Ticking "requires approval" on a
tool in the agent editor reconciles an agent-scoped `approval` rule targeting
`tool:<name>`, and unticking it deletes the row rather than disabling it — the
checkbox is the source of truth. The flag is not persisted alongside the agent's
tool configuration; it is reconstituted from the rules on read, so the two cannot
drift. Every agent-creation path reconciles through the same function, including
bundle install, workspace import and catalog fork.

One naming subtlety is worth knowing when a rule appears not to fire: policy
judges the name the model calls. A code toolset's namespace is collapsed
(`agentarea/shell` becomes `shell`), while an MCP tool keeps the name it
advertises.

The requirement is monotonic across scopes. A workspace that sets
`requires_human_approval` cannot have it turned off by an agent, user or task
layer; the resolver raises a validation error instead of accepting the weaker
document.

No approval rule ships in the default workspace baseline. Human-in-the-loop is
something you opt into.

### Two fields named for approval, one of which does nothing

The API exposes two similarly-named approval fields at different layers. Only one
of them gates anything, and confusing them produces a task that runs unapproved.

**`requires_user_confirmation` on an agent's tool configuration is enforced.**
This is the checkbox described above: transport only, lifted into an agent-scoped
rule, folded into the snapshot under `approval`, and read by the workflow gate. A
tool ticked here does pause the run.

**`requires_human_approval` on `TaskCreate` is not enforced.** It is a public
field in the schema, and it is carried faithfully: into the task row's metadata,
into the execution request, and onto the workflow's goal object. Nothing reads it
after that. The gate consults the policy snapshot, never the goal. Setting it to
`true` and setting nothing else creates a task that runs to completion without
ever asking a human.

The two are not related in code despite the near-identical names. Approval is
granted by a policy rule, and `TaskCreate` has no way to write one.

### The pause

`decide_tool_policy` returns `REQUIRE_APPROVAL` when `requires_human_approval` is
true or the tool is in `escalation_rules`. The workflow's tool gate then:

1. Creates a pending escalation with a fresh id, the tool call id, the tool name,
   its arguments, and the resolved approver list for that specific tool
   (`approvers_by_tool` wins over the global list, falling back to empty).
2. Sets the workflow status to `WAITING_FOR_APPROVAL` and updates the task row to
   `waiting_for_approval`, so the inbox can find it by querying the database.
3. Emits an `approval.request` event with the escalation id, tool name, sanitized
   arguments and the approver list, and publishes it immediately to the event
   stream.
4. Waits on that specific escalation.

Tools awaiting approval stay *disclosed* to the model. Disclosure drops denials,
not escalations — the point of an approval is that the answer might be yes.

### The resolution

A human answers by signalling the workflow with the escalation id, an approve or
deny boolean, an optional comment, and the resolver's user id. The signal handler
is the authorization point:

- If the escalation id is not pending, the signal is ignored.
- If the caller is not permitted to approve, the signal is logged as unauthorized
  and ignored, so the API or activity boundary cannot bypass the policy.
- Otherwise the escalation is marked resolved and an `approval.response` event is
  emitted with the approver's id. Approve and deny share that one wire type; the
  decision is in the payload.

The HTTP response does not tell you which of those three happened. The
resolve-escalation endpoint returns `200` with `{"status": "resolved"}` as soon as
the signal is delivered, and signal delivery is all its success value reports —
Temporal signals return no outcome. An unauthorized caller, or one naming an
escalation that is not pending, receives the same `200 resolved` as a real
approver while the workflow drops the signal and the task stays in
`waiting_for_approval`. Confirm an approval by observing the task leaving that
state or by the `approval.response` event, never by the status code.

On approval the tool call proceeds and the normal `tool.call` event
follows. On denial a tool message saying the call was denied by a human operator,
with the comment, is appended to the conversation so the model can react rather
than retry blindly. Once no escalations remain pending the workflow returns to
running and the task row is set back to `running`.

Whether the caller may approve is decided by `caller_can_approve`:

- An **empty** approver list means any caller may approve. This is a deliberate
  soft default, not an oversight, and it is the state you get from a global
  approval rule with no `approvers` parameter.
- A **non-empty** list is matched literally against `user:<caller_id>`.

## Why not enforce approval in the interceptor pipeline

An `EscalationGuard` exists in the codebase: a gate that reads
`execution_state["escalation_rules"]` and returns `ESCALATE` when the action name
matches a glob. **It is not registered in the pipeline**, and that is intentional.

The interceptor pipeline runs at the Temporal *activity* boundary. An activity
cannot pause and resume — an `ESCALATE` there is converted into an
`EscalationRequired` exception, which fails the activity. The user experience of
that is a failed tool call, not a pending approval, and the conversation state
that would let a human judge the request is not available at that layer.

The workflow is the only place that holds durable state, can wait indefinitely,
can receive a signal, and can put a denial message back into the conversation. So
approval lives there and the guard stays unregistered.

The cost of that choice is coverage: any tool path that does not run through the
agent workflow has no approval flow, only a denial. See the limits below.

## Limits

- **`TaskCreate.requires_human_approval` is inert.** Described above. It is
  writable through the API, reaches the workflow goal, and is read by nothing.
  Per-task approval cannot be requested at task creation; write a policy rule
  instead.
- **`EscalationGuard` is dead code today.** It is defined, tested and never
  registered. If you read it and expect glob-matched approval on LLM calls or
  delegations, nothing wires it up.
- **The MCP proxy denies rather than escalates.** `_authorize_mcp_tool_calls`
  treats anything that is not `ALLOW` as not allowed, so a tool requiring approval
  called through `POST /v1/mcp/{instance_id}/mcp` returns HTTP 403 with no
  escalation created and nothing for a human to answer. An external MCP client
  cannot obtain approval.
- **`SemanticGuard` escalation is not an approval either.** Its medium-severity
  patterns return `ESCALATE` at the activity boundary, which fails the activity.
  No escalation record is created and no human is asked.
- **There is no timeout.** The workflow waits on the escalation with no deadline.
  A task blocked on an approval nobody answers stays in `waiting_for_approval`
  until it is cancelled. There is no auto-deny, no expiry, and no escalation to a
  second approver.
- **Empty approvers means anyone.** A global approval rule written without an
  `approvers` parameter produces an empty list, and an empty list permits any
  caller to resolve. If you want the approval to mean something, name the
  approvers.
- **A rejected approval is indistinguishable from an accepted one over HTTP.**
  The endpoint returns `200 {"status": "resolved"}` on signal delivery, and the
  workflow drops an unauthorized signal with a log line and no reply. A caller
  cannot learn from the response whether the approval was refused, whether the
  escalation id was wrong, or whether it worked. The rejection is recorded only
  in the worker's logs.
- **Group and userset approvers do not grant approval.** `group:<id>` and
  `<type>:<id>#<relation>` references are accepted, validated and stored, but the
  resolution check only matches direct `user:<id>` subjects. An approver list
  containing nothing but group references matches nobody and blocks the task
  indefinitely.
- **No notification is sent.** Core emits the `approval.request` event to the
  stream and updates the task row. It does not send mail, post to a channel, or
  page anyone. Anything that notifies an approver has to consume the event.
- **Approval does not change who acts.** The task continues to execute as the
  original run. An approval by a second person does not re-scope the execution to
  that person's permissions, and the tool activity itself runs under a system
  context rather than either user's.

## Related

- [Tool authorization](/concepts/governance/tool-authorization) — where the
  `REQUIRE_APPROVAL` verdict comes from and which paths it reaches.
- [The policy engine](/concepts/governance/policy-engine) — how approval rules
  merge across scopes.
- [Audit](/concepts/governance/audit) — what an approval leaves behind, and where.
