# Event journal: record first, react by subscription

Status: proposal, for discussion. Nothing here is implemented.
Date: 2026-09-23

## Problem

We want to watch a stream of events (a Twitter/X topic, a competitor blog,
inbound webhooks, our own task lifecycle) and react to only some of them,
while the rest are still kept as "things that happened" that agents can use
as context later.

Today the platform cannot express this. Recording and reacting are fused,
and they are fused in opposite directions on the two sides:

- **External side: no subscription, no intake.** `WebhookManager` starts by
  finding the trigger by `webhook_id`
  (`libs/triggers/agentarea_triggers/webhook_manager.py`), and `webhook_id`
  is a required field of a WEBHOOK trigger. The intake URL exists because a
  trigger exists. An event nobody subscribed to is not ignored; it cannot
  arrive at all. Channel events (Telegram) travel only through the Redis
  stream `agentarea.channel.inbound` and are gone after ack, which goes
  against the rule that events are never Redis-only.
- **Internal side: recorded, but no subscription.** `task.completed` is
  always written to `task_events`, but `TriggerType` only knows CRON and
  WEBHOOK, so nothing can subscribe to it.

The gate that decides whether to react is also weak:

- `evaluate_trigger_conditions` fails open. On an LLM error it falls back to
  rules, and on a second error it returns `True`
  (`trigger_service.py:1468-1481`). On a feed, that means a broken gate
  starts a task for every event.
- The LLM verdict is parsed from free text by substring search
  (`llm_condition_evaluator.py:_parse_evaluation_response`).
- The trigger's model is not passed through; only the global default is
  used.
- A rejected event leaves only a log line. There is no score and no reason,
  so the threshold cannot be tuned from data.

## Proposal

Split recording from reacting.

1. **Journal.** Every event is written to one append-only journal first,
   whether or not anything subscribes to it. The journal has one envelope
   and different `source` values. It has three writers:
   - external intake (webhooks, channels);
   - agent observers, through an `emit` tool;
   - the platform itself (task lifecycle facts, projected from the outbox).
2. **Subscriptions.** A trigger stops owning intake and becomes a
   subscription beside the journal: a source filter, a predicate, and a
   delivery mode. Zero, one or many subscriptions can match the same event.
3. **Novelty from the database, not from the model.** An event carries a
   required natural key. `UNIQUE(source, event_id)` makes a repeat
   observation a no-op. The moment to react is the first successful insert,
   not the moment the model emits. We stop asking an LLM to be a reliable
   diff engine across context boundaries, which it is not.
4. **Relevance from the gate.** Novelty is not relevance: on a topic feed
   every tweet is new. Subscription matching runs after the insert, as a
   pluggable gate (rules, LLM, small classifier), and its verdict is stored.
5. **Context is a read path, not a verdict.** Everything is in the journal,
   so "absorb into context" needs no separate store. An agent reads its slice
   of the journal (for example, "new facts on my subscription since my last
   run") through a tool or through injection into the next run.

### Envelope

Reuse the shape of `resource_usage_events` (source, event_id, kind,
occurred_at, data JSONB, `UNIQUE(source, event_id)`), which is already
proven in production. Do not reuse the table: it is DB-guarded append-only
and has a different retention and meaning.

```
journal_events
  sequence      bigint identity  primary key
  workspace_id  text             not null
  source        text             not null   -- webhook:{id} | channel:{type}:{id} | trigger:{id} | platform
  event_id      text             not null   -- natural key, required, no default
  kind          text             not null   -- free string chosen by the writer
  occurred_at   timestamptz      not null
  received_at   timestamptz      not null default now()
  data          jsonb            not null
  unique (source, event_id)
  -- partitioned by received_at, retention per workspace
```

```
subscription_matches
  subscription_id (trigger_id), event_sequence, verdict, score, reason,
  gate_backend, task_id nullable, evaluated_at
```

Two rules are fixed from the start:

- **`kind` is a free string, not a schema registry.** Making a user design a
  fact schema before watching a blog kills the feature. A schema can be
  frozen later, once similar facts pile up.
- **The natural key is required, with no default and no silent hash of the
  body.** If a writer cannot say what makes this fact different from the
  next one, the fact is invalid and the write fails loudly.

### Gate

- **Fail-closed.** A gate error means no reaction, and the error is recorded
  on the match row.
- **Structured output.** The verdict comes back as `{verdict, score, reason}`,
  not as prose.
- **Pluggable backend.** `rule` | `llm` (litellm, per-subscription model) |
  `classifier` (a small constrained-decision model; Laya is a candidate once
  it has a non-MLX runtime, because prod is Linux).
- **Batched and off the consumer hot path.** Today the inbound consumer
  handles messages strictly one after another, with an LLM call inside
  (`inbound_subscriber.py:95-96`).

### Delivery

This is set per subscription:

- `per_event`: one matched event starts one task, with a budget per window;
- `window`: matched events are collected and start one task per window.

Inbox needs no change. Processing a fact turns it into a task, and tasks
already reach the inbox.

## What this buys

- **Retroactivity.** A subscription separated from intake can be pointed at
  the past: "run this agent over the forty tasks that failed last month",
  or "which of last week's tweets would this predicate have matched". While
  the trigger owns intake, this question cannot even be asked. This is the
  real payoff of recording the unimportant: the right to change your mind.
- **Tuning.** Every verdict is stored with a score, so thresholds can be
  tuned on real data, and this plugs into the eval module.
- **Visibility.** "Seen 1000, reacted to 3."

## Costs and risks

- **Volume is no longer implicitly bounded.** "No trigger means nothing
  arrives" was a hidden limit. Retention and per-workspace quotas are a
  launch requirement, not a follow-up.
- **Public intake needs a rule.** Accepting anything at a public URL is an
  open tap. Open question below.
- **The rework is not cosmetic.** `webhook_manager.py` (~50 KB) and
  `trigger_service.py` (~62 KB) are built around "the trigger finds itself
  by `webhook_id`".
- **Journaling the internal side selectively.** Only lifecycle facts are
  projected, not `llm.call.chunk` and similar. `task_events` stays the
  task-feed store.
- **Cron + agent observers are expensive.** N watched targets per hour is N
  tasks with an LLM that find nothing 95% of the time.

## Not doing

- No columnar store (ClickHouse) and no CEP window rules. There is no load
  for them yet, and matching and retrieval are not analytical scans. The
  journal sits behind one writer port, so the engine can be swapped later.
- No separate "source" or "channel" entity. Production intake is webhooks
  (Telegram uses `setWebhook`). The Go poller exists for local development
  without a public URL.
- No merge with `task_events`.

## Open questions

1. **Where to start.** The internal side already records, and only
   subscriptions are missing, so starting there needs the smaller change.
   The external side is what the Twitter case needs, but it requires
   reworking the webhook path.
2. **Unverified intake.** Option (a): record a request that fails signature
   verification as a truncated fact (metadata and fingerprint, no body)
   under a hard quota. Option (b): reject it at the edge and only count it
   in `audit_events`. The author of this doc leans to (b), because it keeps
   the journal free of third-party noise.
3. **Cheap collection without an LLM.** Is it a separate step kind (fetch,
   parse, emit keys) with the agent called only on novelty, or does
   everything go through the agent at first? Suggestion: no new step kind
   yet. Cheap collection for external data already exists as webhooks from
   Apify, n8n or similar. The agent-emitter is for pages without an API.
   Revisit once the cost is measured.
4. **How an agent reads its context.** Pull on demand through a tool, or
   inject new facts into the next run automatically.

## Prerequisite that stands on its own

The gate fixes can land before any of the above, and are worth it even if
the journal is rejected:

- fail-closed;
- structured verdict;
- per-trigger model;
- verdict persistence.
