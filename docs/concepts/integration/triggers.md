---
title: Triggers and channels
type: concept
description: "How an agent starts without a person asking, and how its output reaches the place the request came from."
prerequisites:
  - /concepts/execution/tasks
related:
  - /concepts/integration/event-streams
  - /concepts/execution/events
  - /concepts/execution/durable-execution
  - /concepts/governance/budgets-and-quotas
last_updated: 2026-10-19
---

Everything else in AgentArea assumes a person made a request. A trigger is what
starts a task when nobody did: a schedule comes due, or an event arrives in a
stream. A channel is the other half: where the answer goes, which is usually
back to whatever produced the input.

The two meet at the task. A trigger creates a task and stamps it with a
delivery address. The delivery group sends the task's events to that address.
Neither knows about the other except through the task.

## The problem

An agent that only runs when someone clicks is a tool. An agent that runs on a
schedule, or when a pull request opens, is infrastructure, and infrastructure
that acts on its own needs answers to questions a manual run never raises.

What stops a broken trigger from running forever? A cron expression that fires
every minute against an agent whose model is misconfigured spends money and
fills the task table until someone notices.

What happens to the schedule when the process restarts? Scheduling inside the
API process means a deploy silently drops every timer.

Where does the answer go? A task started from a Telegram message that finishes
by writing to the dashboard has failed at its actual job. And who is allowed to
start it? A bot anyone can message is a door to the agent.

How does the platform decide whether an event deserves a run at all? Most
webhook payloads are noise. Filtering them in the agent means paying for a run
to conclude "nothing to do".

## How AgentArea approaches it

**A trigger is a stored record, not a running thing.** `Trigger` carries the
agent it starts, the `task_parameters` used to build the task, a `conditions`
block, and its own safety counters. There are two types:

| Type | Key fields | Fires when |
|---|---|---|
| `cron` | `cron_expression`, `timezone` | The schedule comes due |
| `stream` | `stream_id`, `event_filter`, `session`, `batch` | An event in that stream matches the filter |

A webhook is not a trigger type. A provider's webhooks arrive at a source of an
[event stream](/concepts/integration/event-streams), and a `stream` trigger
subscribes to that stream. One stream can feed any number of triggers, and a
trigger can sit on a stream that a forward, a processor or the platform writes.

**Cron triggers are Temporal schedules, not in-process timers.** Creating one
creates a Temporal schedule with id `cron-trigger-<trigger_id>` from the cron
expression and time zone. The schedule lives in Temporal, so it survives a
restart of every AgentArea process, and it is visible and pauseable through
Temporal like any other schedule.

**A stream trigger fires once per event, after intake has answered.** The
trigger's subscription reads the stream from the moment it was created. For
each event its `event_filter` admits, the trigger checks, in order:

1. it is active, or the reaction is `skipped` with "trigger is inactive";
2. the event is not deeper than `AGENTAREA_EVENT_FORWARD_DEPTH`, and does not
   come from a task this trigger started;
3. the sender is admitted, when the source's catalog entry asks for admission;
4. whoever configured the trigger may still run its agent;
5. its conditions are met.

The task id is derived from the subscription and the event, so a redelivered
event never starts a second task. The reaction (`reacted` with the task,
`skipped` with a reason, or `error`) is recorded once per event and shown on the
event in the events feed.

**Sessions keep a conversation in one task.** An event carries a `session_key`
when its catalog entry names one, such as a chat or a thread. With
`session: {"continue": true, "idle_timeout": "30m"}`, the next event of the same
session joins the running task instead of starting a new one. Without
`session`, the trigger continues sessions when the source type has them, and
the idle timeout is 30 minutes.

**A batch window fires once for many events.** A stream trigger with
`batch: {"window": "1h", "max_events": 50}` does not fire per event. Each event
that passes the checks above, conditions included, joins the trigger's open
batch, and its reaction is recorded as `batched`. The batch is a Temporal
workflow. It opens with its first event and fires when the window has passed
or `max_events` have joined, whichever comes first. Either may be left out, and
no batch holds more than `AGENTAREA_TRIGGER_BATCH_MAX_EVENTS` (100 by default).
The task the batch starts is told every event under `events`, each `batched`
reaction is settled with that task, and the task replies to the newest event's
address. Events a messenger admitted carry their sender's authority, so each
admitted sender gets a batch of their own. Switching the trigger off or
deleting it skips the events held in its open batch.

<Note>
Batch windows are being finished. This section describes the code as it is
today and can change before release.
</Note>

**Conditions are evaluated before a task is created,** and by default by a
model. A condition with no `type` is an `llm` condition: it names the chat or
decision model instance that judges it in `model_id`, and the model's verdict
and reason are recorded on the reaction. `rule` and `combined` conditions are
the deterministic path. The point is filtering noise without writing a parser
per provider. The cost is a model call per candidate event, which the
[Limits](#limits) section revisits.

**A messenger admits senders, not anyone who writes.** A catalog entry with an
`admission` block, today Telegram's, lets an event through only from a sender
linked to a platform user. A person links their Telegram account from inside
Telegram with a code they asked for while signed in, then `/confirm`. A linked
sender is admitted only when the authorization graph lets them run the agent,
and the task runs as that person, not as whoever configured the trigger.
Everyone else is refused and the reaction is `skipped`: an unlinked sender is
told at most once a day how to link, a linked sender without access is told
they have none, and group chats and other bots are ignored.

**A trigger stops when its configurer loses access.** Before firing, the
trigger checks that the person who configured it is still a member of the
workspace and may run its agent. If not, the trigger is stopped and marked
`needs_owner`, and the reaction is an `error` naming why. Enabling it again
clears the mark; the next event checks again.

**A trigger disables itself before it does damage.** Every trigger has a
`failure_threshold` (default 5, bounded 1 to 100) and a `consecutive_failures`
counter. What counts is how the run ends, not that it started: a firing that
could not start its task counts, and so does a task that failed, whose firing
is then marked `failed` with the task's error. A completed task resets the
counter; crossing the threshold takes the trigger out of service and pauses a
cron schedule. A firing turned away by its conditions and a task a person
cancelled neither count nor reset. Nothing external has to notice a broken
trigger.

**The agent is told what started it.** A task's first message is the ask: the
trigger's task text when it has one, which says what to do. Only a trigger
without one, such as a chat channel, takes the incoming message's text as the
ask. One block follows, the same for every source: the trigger's name and type,
the stream, the event's kind, key and received time (UTC), then the event's
data as JSON under a notice that it is data from an outside sender, not
instructions. Credential headers are already removed. Data over 16 KB is never
cut: the block names a task input file, `inputs/attachments/trigger-event.json`,
which the run writes into the task's own workspace before the agent starts. A
schedule tick carries no event, so its message is the task text alone.

### Channels carry the output back

**A task an event started replies through its delivery address.** When a
trigger fires on an event, it builds the address from the source that brought
the event and the `reply` block of that source's catalog entry: which reply
sender, which target (a chat id, a thread, a mail address read out of the
event), which credentials, and how much of the run to show. A copy of an event
made by a forward or a processor has no address; only the original's task
answers the sender. An event whose entry has no `reply` block, or that names no
target, starts a task that does not reply.

| Reply sender | Used by | Shows |
|---|---|---|
| `http` | Slack, Discord, from the entry's `reply.request` | `concise`: result, questions to the user, status |
| `telegram_live` | Telegram: one message edited in place as the run goes | `concise` |
| `smtp` | email and IMAP sources | `summary`: result and questions, at the end |
| `task_webhook` | the webhook a caller gave when starting a task | |
| `a2a_webhook` | A2A push notification configs | |

**Delivery is a consumer group, not an inline call.** A run publishes its
events once to `tasks.events` and does not know who reads them. The `delivery`
group reads every task event, looks up where its task replies (the delivery
address, the caller's task webhook, A2A push configs) and sends each one that
shows the event. Each target is retried on its own and marked delivered only
after its send succeeds. A target that fails for good goes to
`tasks.events.delivery.dlq` naming that target, so a replay sends there only. A
slow messenger API therefore cannot block the agent loop, and a crashed sender
loses nothing. See [The event bus](/concepts/integration/event-bus).

## Why not cron inside the API process

It is one dependency fewer and a few lines of code.

It fails the moment you run more than one API replica, because every replica
fires the same schedule. It fails again on every deploy, because in-process
timers die with the process that holds them and nothing records that they were
due. Temporal is already required to run tasks at all, and it already solves
this: durable schedules with a visible history. Adding a second, weaker
scheduler next to it would mean maintaining two.

## Why conditions default to a model rather than a rule language

A rule language is cheaper, deterministic, and testable, and for a payload shape
you control it is the better tool.

The case triggers actually face is the opposite: a webhook body whose shape is
set by a third party and changes without notice, where the interesting question
is semantic ("is this issue actually a bug report") rather than structural. A
rule language answers that by growing into a small programming language, and
every provider needs its own. The trade accepted here is a model call per
candidate event, made explicit rather than hidden, with `rule` conditions and
the stream filter still available for the structural cases.

## Limits

**Condition evaluation costs a model call per candidate event.** With an `llm`
condition, a high-volume stream pays for one inference per event the filter
admits, after the webhook's `202` and before any task exists, so the spend does
not appear against the agent's task budget. Narrow the `event_filter` first.

**A disabled trigger's stream keeps recording.** Disabling a trigger, by hand or
by crossing `failure_threshold`, does not touch the stream or its sources:
deliveries are still recorded and answered. Only the firing is skipped, with
the reason "trigger is inactive". Re-enabling the trigger does not replay what
was skipped while it was off.

**A trigger that disables itself stays disabled.** Nothing re-enables it when
the underlying problem is fixed. Re-enable it explicitly after fixing the cause.

**Only entries with a `registration` block register their webhook.** Telegram
and MCP Events sources are registered with the provider by the event service.
Every other provider has to be pointed at the source's URL by hand, and nothing
reports that this step was skipped.

**Sender admission exists for Telegram only.** Other messengers with a `reply`
block, such as Slack and Discord, admit any sender the provider delivers, and
the task runs as the trigger's configurer.

**A batch replies to one address.** A batch's task answers the newest event's
sender only, even when its events came from several chats.

**The channel registry is per process.** Reply senders register into an
in-memory registry when the worker starts. A process asked for a sender it
never registered gets nothing back.

## Related

<Columns cols={2}>
  <Card title="Event streams" icon="lightbulb" href="/concepts/integration/event-streams">
    Sources, the event envelope, and the subscriptions a trigger is one of.
  </Card>
  <Card title="The event bus" icon="lightbulb" href="/concepts/integration/event-bus">
    The delivery group and how task events reach a channel.
  </Card>
  <Card title="Tasks" icon="diagram-project" href="/concepts/execution/tasks">
    What a trigger creates, and the states it can reach.
  </Card>
  <Card title="Durable execution" icon="diagram-project" href="/concepts/execution/durable-execution">
    The Temporal machinery cron triggers and batches reuse.
  </Card>
  <Card title="Budgets and quotas" icon="scale-balanced" href="/concepts/governance/budgets-and-quotas">
    Why unattended runs need a ceiling.
  </Card>
</Columns>
