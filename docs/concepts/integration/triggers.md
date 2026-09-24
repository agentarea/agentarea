---
title: Triggers and channels
type: concept
description: "How an agent starts without a person asking, and how its output reaches the place the request came from."
prerequisites:
  - /concepts/execution/tasks
related:
  - /concepts/execution/events
  - /concepts/execution/durable-execution
  - /concepts/integration/mcp
  - /concepts/governance/budgets-and-quotas
last_updated: 2026-09-13
---

Everything else in AgentArea assumes a person made a request. A trigger is what
starts a task when nobody did: a schedule fires, or an external system posts to a
URL. A channel is the other half — where the answer goes, which is usually back
to whatever produced the input.

The two are separate systems that meet at the task. A trigger creates a task; a
channel delivers that task's events somewhere. Neither knows about the other
except through the task.

## The problem

An agent that only runs when someone clicks is a tool. An agent that runs on a
schedule, or when a pull request opens, is infrastructure — and infrastructure
that can act on its own needs answers to questions a manual run never raises.

What stops a broken trigger from running forever? A cron expression that fires
every minute against an agent whose model is misconfigured will spend money and
fill the task table until someone notices.

What happens to the schedule when the process restarts? Scheduling inside the
API process means a deploy silently drops every timer.

Where does the answer go? A task started from a Telegram message that finishes
by writing to the dashboard has failed at its actual job.

And how does the platform decide whether an event deserves a run at all? Most
webhook payloads are noise. Filtering them in the agent means paying for a model
call to conclude "nothing to do".

## How AgentArea approaches it

**A trigger is a stored record, not a running thing.** `Trigger` carries the
agent it starts, the `task_parameters` used to build the task, a `conditions`
block, and its own safety counters. Two concrete types subclass it:

| Type | Key fields | Fires when |
|---|---|---|
| `cron` | `cron_expression`, `timezone`, optional `data_extractor` | The schedule matches |
| `webhook` | `webhook_id`, `allowed_methods`, `webhook_type`, `validation_rules` | A request arrives at that webhook's URL |

**Cron triggers are Temporal schedules, not in-process timers.** Creating one
calls `create_schedule` with id `cron-trigger-<trigger_id>` and a
`ScheduleSpec(cron_expressions=[…], time_zone_name=…)`. The schedule lives in
Temporal, so it survives a restart of every AgentArea process, and it is visible
and pauseable through Temporal like any other schedule.

**Webhook triggers get an unguessable id.** When `webhook_id` is omitted at
creation the platform generates one with `secrets.token_urlsafe(16)`. The URL is
the credential for a `generic` webhook, which is why it is not derived from the
trigger name.

**Webhook types are open, not enumerated.** `WebhookType` names the ones the
platform knows — `telegram`, `slack`, `github`, `discord`, `linear`, `stripe`,
`gmail`, `teams`, `generic` — but its `_missing_` accepts any string, so a
deployment can configure a type the enum never heard of instead of being
rejected.

**A trigger disables itself before it does damage.** Every trigger has a
`failure_threshold` (default 5, bounded 1–100) and a `consecutive_failures`
counter. A success resets it; crossing the threshold takes the trigger out of
service. This is the answer to "what stops a broken trigger" — nothing external
has to notice.

**Conditions are evaluated before a task is created,** and by default they are
evaluated by a model. A condition's `type` defaults to `llm`, which sends the
payload and the condition text to a model instance through litellm and acts on
the verdict. The point is filtering noise without writing a parser per provider;
the cost is a model call per candidate event, which the [Limits](#limits)
section revisits.

**Every attempt is recorded, whether or not it produced a task.**
`TriggerExecution` stores `status` (`success`, `failed`, `timeout`,
`cancelled`), the `task_id` if one was created, `execution_time_ms`, the error,
and the Temporal `workflow_id` and `run_id`. A trigger that silently stopped
producing tasks is diagnosable from its own history.

### Channels carry the output back

A channel is an outbound adapter with two jobs: format a workflow event for its
destination, and send it there. Adapters register into a process-local registry
by name:

| Channel | Outbound delivery | Registers its own inbound webhook |
|---|---|---|
| `telegram` | Yes — streaming sender when Redis is configured, otherwise plain HTTP | Yes |
| `slack` | Yes | No |
| `discord` | Yes | No |
| `email` | Yes | No |
| `a2a_webhook` | Yes — client-supplied webhooks, delivered as A2A events | No |

The split in that last column is deliberate. Only a provider that *pushes*
updates to a URL you registered needs a registrar; a channel that polls or holds
a gateway connection has none, and the orchestrating service treats the absence
as a no-op rather than an error.

**Delivery is a stream job, not an inline call.** The workflow emits to an
outbound stream; a consumer reads it through a Redis Streams consumer group,
deduplicates, calls the adapter, then acknowledges, requeues, or dead-letters.
A separate autoclaimer re-delivers messages left pending by a consumer that
died. A slow Telegram API therefore cannot block the agent loop, and a crashed
sender loses nothing.

## Why not cron inside the API process

It is one dependency fewer and a few lines of code.

It fails the moment you run more than one API replica — every replica fires the
same schedule — and it fails again on every deploy, because in-process timers die
with the process that holds them and nothing records that they were due.
Temporal is already a required dependency for running tasks at all, and it
already solves exactly this: durable schedules with a visible history. Adding a
second, weaker scheduler next to it would be a choice to maintain two.

## Why conditions default to a model rather than a rule language

A rule language is cheaper, deterministic, and testable, and for a payload shape
you control it is the better tool.

The case triggers actually face is the opposite: a webhook body whose shape is
set by a third party and changes without notice, where the interesting question
is semantic — "is this issue actually a bug report" — rather than structural. A
rule language answers that by growing into a small programming language, and
every provider needs its own. The trade accepted here is a model call per
candidate event, made explicit rather than hidden, with the deterministic path
still available by setting an explicit condition `type`.

## Limits

Verified against the code on 2026-09-13. Where this section and the model above
disagree, this section describes what a deployment actually gets.

<Warning>
**`polling` is a declared type with no implementation.** `TriggerType.POLLING`
exists in the enum and the API DTO maps the string `"polling"` onto it, but
there is no polling domain model, no scheduler, and no execution path — unlike
`cron` and `webhook`, which have both. A trigger created as `polling` is
accepted and then does nothing. Use a `cron` trigger with a `data_extractor` for
periodic fetching.
</Warning>

**Condition evaluation costs a model call per candidate event.** With the
default `llm` condition type, a high-volume webhook pays for one inference per
delivery *before* any task exists, so the spend does not appear against the
agent's task budget. Size the source, not the agent.

**The adapter registry is per-process.** Adapters register on import and on a
configuration call, into an in-memory dict. A channel is available to a process
that registered it; there is no shared registry to query and no error if a
process is asked for a channel it never registered — `get_adapter` returns
`None`.

**Only Telegram registers its own inbound webhook.** Every other channel that
needs a provider-side webhook has to be pointed at the platform by hand, and
nothing in the platform reports that this step was skipped.

**A trigger that disables itself stays disabled.** Crossing `failure_threshold`
stops the trigger; nothing re-enables it when the underlying problem is fixed.
Re-enable it explicitly after fixing the cause, or the schedule stays silent.

**Signature verification is opt-in, for every type — including `github` and
`stripe`.** `verify_webhook_signature` first resolves a signing secret from the
trigger's `validation_rules` and `webhook_config`. With no secret it returns
`None`, meaning "not enabled", and the request proceeds. A `github` webhook
created without a secret is no more verified than a `generic` one; the
unguessable `webhook_id` is then the only thing protecting it.

When a secret *is* configured, the verifier is chosen by type — `slack`,
`github`, `discord` (Ed25519), `linear` and `stripe` have dedicated verifiers,
`generic` uses a configurable HMAC whose header, algorithm and prefix come from
`validation_rules`, and Telegram is validated by bot token at a different layer.
A configured secret that fails to verify rejects the request, as does a
configured secret with no raw body to check.

## Related

<Columns cols={2}>
  <Card title="Tasks" icon="diagram-project" href="/concepts/execution/tasks">
    What a trigger creates, and the states it can reach.
  </Card>
  <Card title="Events" icon="diagram-project" href="/concepts/execution/events">
    What a channel formats and delivers.
  </Card>
  <Card title="Durable execution" icon="diagram-project" href="/concepts/execution/durable-execution">
    The Temporal machinery cron triggers reuse.
  </Card>
  <Card title="Budgets and quotas" icon="scale-balanced" href="/concepts/governance/budgets-and-quotas">
    Why unattended runs need a ceiling.
  </Card>
</Columns>
