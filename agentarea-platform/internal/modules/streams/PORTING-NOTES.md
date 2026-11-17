# streams: porting notes

Python paths are relative to `agentarea-platform/`. Dossier: `.omc/research/go-migration/dossiers/streams.md`.

## Mounted routes

- Streams: GET/POST `/streams/`, GET/DELETE `/streams/{id}`, GET `/{id}/subscriptions`, POST `/{id}/forwards`,
  DELETE `/{id}/subscriptions/{sub}`, POST `/{id}/processors`, PATCH/DELETE `/{id}/processors/{sub}`,
  GET `/{id}/subscriptions/{sub}/outcomes`.
- Events: GET `/streams/events` (feed with facets on the first page), GET `/streams/events/live` (SSE; 503 when the
  broker is not wired), GET `/streams/events/{event_id}`, GET `/{id}/events`, GET `/{id}/events/{sequence}`.
- Triggers: CRUD, enable, disable, health, executions, status, metrics, timeline, correlations; POST `.../execute` and
  `.../run` (only when runs' `Tasks` is wired).
- Sources: GET `/streams/source-types`, GET/POST `/{id}/sources`, PATCH/DELETE `/{id}/sources/{sid}` (when the catalog
  source types, secrets and secret catalog are wired).
- Webhook sink at the root: GET `/webhooks/health`, POST `/webhooks/{webhook_id}` (when catalog, secrets, bus and dedup
  are wired). Order of answers: 429 rate limit (per webhook id, fails open) → 413 (25 MiB, declared then streamed) →
  400 unparseable → 422 NUL in text → 404 unknown webhook → 400 not a catalog webhook type → 503 credentials or secret
  store unreachable → 401 verification failed → 200 handshake → 200 ended → 429 quota → 202 accepted|duplicate.
  Schemes: hmac, hmac_timestamped (plain, kv, list; 300 s window), shared_token, ed25519, api_lookup (netguard vendor
  client, no redirects, 10 s), whsec secrets; constant-time compares. Bodies over 64 KiB move to the workspace files.

All 41 operations of the `streams` tag are mounted when their ports are wired.

## Background parts (events role)

- Router (`router/`): partitioned `streams.events`, a 60 s per-stream subscription cache invalidated by
  `streams.subscriptions.changed`; trigger, forward, processor (sandbox harness: 10 s, 256 KiB, ≤100 outputs) and
  external handlers; events view; live notices `event.recorded` / `event.processing`; trigger batches as a durable
  signal-with-start of `TriggerBatchWorkflow`. `Module.Consumers()`.
- Fire (`service/fire*.go`): Python's order (inactive, manual execute check, agent gone → needs_new_owner, saved task
  definition, idempotent retry, cron overlap, spend cap, failure threshold auto-disable with `trigger.auto_disabled`).
- Event-service merge: `polling/` (manager, loop, http_json/feed/imap/mcp_events transports, MCP Events client, Redis
  claims `polling:claim:<id>`, drain of the old `streams.ingest` backlog) and `delivery/` (external webhook delivery,
  expired-subscriber sweeper). Polled items and gaps take the webhook path in-process (`source.gap`). Its own secrets,
  egress, publisher, telemetry, health server, config loader and DB driver are dropped for the kernel's. Env: reused
  AGENTAREA_EVENT_POLL_INTERVAL, AGENTAREA_EVENT_MAX_POLLERS, AGENTAREA_EVENT_WORKER_ID, AGENTAREA_MCP_MANAGER_URL,
  AGENTAREA_MCP_GATEWAY_SECRET; no new names.
- `events` role (`app/events.go`): outbox relay with identity's `MembershipRemovalHandler()`, `Module.Consumers()`,
  pollers, delivery consumers. Serve mounts the sink with its own bus/dedup/quota; a missing Redis leaves it unmounted.
- Task replies (`replies/`, `Module.Replies`, events role): the delivery group on `tasks.events` (worker
  `TaskEventDelivery` + `StreamAutoclaimer`, main.py:375-435). Targets are the task's `delivery_address` parameter
  (sender http, telegram_live, smtp) and its `task_webhook` metadata (signed POST, silent presentation); visibility,
  dedup keys `<event>:<target>` and `dead:<event>:<target>`, MAX_ATTEMPTS dead-lettering to
  `tasks.events.delivery.dlq` with `delivery_target`, and a one-target replay as Python. Env: the existing
  AGENTAREA_CHANNEL_{AUTOCLAIM_IDLE,AUTOCLAIM_EVERY,DEDUP_TTL,BLOCK,BATCH_SIZE,MAX_ATTEMPTS}; no new names. Runs gained
  `api.TaskOutcomes` (`Surface.TaskOutcomes()`, a pure read of the task's owner, origin, parameters and metadata).
- Task-event groups (`Module.TaskEventConsumers`, events role): `platform` (PlatformProjection: completed, failed,
  cancelled, approval and input requests into the workspace's `platform` stream, created by `platform` on first use)
  and `trigger-outcomes` (TriggerRunOutcomes: a failed run of a trigger marks its firing failed and counts toward
  `failure_threshold`, auto-disabling as a failed firing does; a completed run resets the count).
- Read-model partitions (`partitions/`, `store/partitions.go`, wired by `app/partitions.go` in the events role, which runs
  the events view): PartitionMaintainer hourly, a failed first pass stops the process. Same advisory key, lock_timeout
  5 s with deferral, yesterday through AGENTAREA_EVENT_PARTITIONS_AHEAD days created, days past
  AGENTAREA_EVENT_RETENTION dropped with their `stream_event_counts`, AGENTAREA_EVENT_ARCHIVE writes
  `event-archive/<quote(ws)>/<day>.jsonl.gz` (RoutedEvent JSON lines) to AGENTAREA_S3_BUCKET first and keeps a day the
  store refuses. Spools go to a temp file always (Python: memory up to 8 MiB). Archive pages by (workspace, sequence),
  500 a page, on the read pool.

## Ports for other modules and the runs mapping

- `api.Triggers` (agents' TaskDefTriggers, insights topology) and `service.Scheduling` (`Module.Scheduling()`).
- `api.AgentTriggers` (`Module.AgentTriggers()`, agents' create-agent `triggers`): `Check` decodes each TriggerSpec strictly (422, loc `body.triggers.<i>.<field>`), then runs `Service.CheckNew` (the shared `validateNew` also used by `Service.Create`, stream existing, read on it; 400 `Trigger '<name>': ...`); `Create` makes them in order through `Service.Create` and deletes the made ones on a failure. Spec-level schema checks (session/batch patterns, reserved, model_override, reasoning) answer 422 here, 400 on the trigger routes.
- Runs declares `service.Triggers` with its own types (`CronTrigger`, `TriggerState`, `TriggerFire`, `TriggerFiring`,
  `TriggerExecutionRecord`, `RecordedTriggerExecution`, `TriggerBatch`, `TriggerBatches`). Streams keeps its shapes in
  `streams/api` (`CronRow`, `TriggerState`, `ExecutionRecord`, `RecordedExecution`, …) and does not import `runs/service`.
  The adapter in `app/` maps them field by field; the names match one to one.
- Streams consumes runs through `runs/api.Tasks` (Submit) directly, plus `api.TaskReads{Statuses, Costs}` and
  `api.FiringTasks` that `app/runs_tasks.go` adapts from runs' `api.TaskReads`/`api.FiringTasks` (`Surface.TaskReads()`,
  `Surface.FiringTasks()`) and agents' `api.Standing` (agent status, saved task definition). Serve and events build
  runs' surface with the same `newRunsSurface`.
- Catalog gained `api.SourceTypes` (`Module.SourceTypes()`): a pure read of `registry_items` of type `source_types`.

## Blocked (needs another module's api)

- MCP Events sources read the instance through connections' `MCPEventSources` (app adapts it).
- No sandbox processor runner yet: the `events` role starts with a warning and every processor reaction is retried
  until dead-lettered.

## Deviations (kept)

- No task title: Python's `title=f"Trigger: {name}"` was never stored (tasks has no title column) nor sent to the
  workflow, so nothing read it. Python stored the ask as description and sent ask + event block as the workflow query;
  Go stores and sends the full message (a restarted task in Python lost the event block).
- Trigger conditions: rule, combined and legacy `field_matches` are evaluated as Python does (`domain/conditions.go`,
  Python's ==, ordering and str() over JSON; TypeErrors in Python's words), at fire, batch join and the cron
  condition activity; a verdict's skip and score are recorded. Integral JSON floats read as ints (5.0 is 5); dict
  keys iterate sorted.
- LLM conditions (`service/llm.go`, `domain/llm_conditions.go`): a chat model answers the prompt as JSON, a decision
  model answers System One's `condition_met` choice; the instance must be chat or decision at save. Each call goes
  through runs' `OneShotModels` (spend caps of the trigger's agent, billing hold, charge, a task-less model line with
  `purpose`/`trigger_id`). The line carries the trigger's agent_id (Python wrote None), so the agent's caps count it.
  No `TRIGGERS_LLM_ENABLED` switch: Python's default (on) is the only behaviour.
- `llm_parameter_extraction`: Python named no model for the call, so it always failed and was logged; Go asks the
  agent's own model. Extracted keys never override a set parameter, a reserved one, or a resource key
  (mcps, mcp, mcp_servers, skills, files). A failure is logged and the task starts without them.
- Telegram sender admission (`service/admission.go`) runs on identity's `MessengerLinks` (holder, link-code
  redeem and `/confirm`); refused senders hear why once a day (`telegram-sender-notice`).
- A2A push notifications are not sent: nothing writes `a2a_push_configs` (Python's helpers are unused and Go has no
  A2A tasks), so the delivery group has no A2A target.
- A platform event's summary of a non-string value is compact JSON (Python: `str()` of the dict).
- Templates: an unknown placeholder kind or an object inside text renders absent instead of raising TemplateError; the
  mcp_events schema check covers the top level only; extra top-level SourceCreate fields are ignored.
- Trigger create/update refuses an archived agent with "Agent with ID X does not exist" (Python: "Agent X is archived;
  restore it first"); `app` adapts agents' `Standing` to "exists and is not archived".
- `task_definition_id` on a trigger is not checked to exist (needs a runs read port).
- Request quirks are not chased (owner update): malformed JSON and bad path UUIDs answer 400 from the generated wrapper.
- Naive `start_time` is refused (the generated binder takes RFC 3339); no client sends one.
- Timeline and correlation times are UTC with `Z`; trigger health drops the Temporal namespace.
- Cron day-of-month/day-of-week AND semantics are Temporal's: streams validates the expression (Python's grammar and
  messages) and computes no run times.
- The processor code check is a Python tokenizer, not CPython's parser: every refusal Python makes for empty code, size,
  no `def process(<positional>)`, a secret-shaped constant or assignment (via `MaskInlineSecrets`), and the tokenizer
  level syntax errors (unclosed/mismatched brackets, unterminated strings, indentation, missing block, bytes/str mix) are
  made with CPython 3.11's messages; an expression-level syntax error (`x = 1 +`) is accepted here and fails at run time
  as an error reaction. When two secrets sit in one code, Go reports the lowest line; Python reports the first node of
  `ast.walk` (breadth first), which can be a later line.
- `robfig/cron` stays in go.mod as `// indirect` until a tidy.

## Fixed Python bugs

- `NotAForwardError` for a processor said "belongs to trigger None, not a forward; it is removed by deleting the trigger".
  Deleting a processor through `/subscriptions/{id}` now says "Subscription X is a processor, not a forward"
  (`domain/stream.go` NotAForward; handlers `TestProcessors`).
- `get_execution_timeline` ignored `bucket_size_minutes` and always bucketed hourly (service `TestExecutionReads`).
- `temporal_schedule_manager.py:394-403` `recent_actions` fields were always null; Go fills scheduled/actual time and the
  workflow id (no test: needs Temporal).
- `triggers.py:1108,1147` turned `require_permission`'s 403 into a 500 with a blanket except; Go answers 403
  (handlers `TestExecuteAndRunAnswer403NotA500`).
- A provider time of inf/nan/out of range raised OverflowError, a 503 retry loop; the time is left unset (domain
  envelope test).
- `compare_digest` on a non-ASCII value raised TypeError (500); Go compares bytes (verification tests).
- `add_source`/`delete_source` wrote the source, its credentials and references in separate steps; now one transaction
  with the reference staged (service `TestAGithubSource…`, `TestAPickedSecret…`).
- Event service: pollers registered at API_URL even when AGENTAREA_TELEGRAM_WEBHOOK_URL was set
  (`TestPollersRegisterAtTheURLTheAPIShows`); a malformed poll interval / max pollers was ignored, now fails startup
  (`TestAMalformedPollSettingFailsStartup`); one never-ingestable item held the cursor forever, now logged and skipped
  (`TestAnItemNoRetryCanIngestDoesNotHoldTheCursor`).

- `libs/triggers/agentarea_triggers/channels/markup.py:106,110` (and `email.py:62`): `str(d.get('error', 'Unknown
  error'))` said "None" for a null error; a null reads as missing (replies `TestFormatEvent`).
- `markup.py:143` `limited` could cut between a MarkdownV2 escape and its character, leaving a lone `\` Telegram
  refuses to parse; the cut drops it (replies `TestLimitedNeverEndsOnALoneEscape`).
- `email.py:171` `int(smtp_creds.get("smtp_port", 25))` raised ValueError on a non-numeric port, retried until
  dead-lettered; it is final at once (replies `TestEmailPortThatIsNoNumberIsFatal`).

## Fixed Go-port bugs

- `domain.Session`/`Batch` lacked JSON tags (idle_timeout, max_events lost) and `InsertTriggerSubscription` bound one
  parameter to a timestamptz and a timestamp column, so stream-trigger create failed (`TestStreamTriggerFilterAndClears`).
- PUT now reads the raw body: null clears `task_definition_id`, `session`, `batch`; absent keeps them.
- `event_filter` is validated as pydantic `EventFilter` (`domain.ParseEventFilter`) and stored as its `model_dump`.
- Enable resets `consecutive_failures`; `streams.subscriptions.changed` is written to the outbox on every subscription
  change (stream delete, forward/processor create, update, delete, trigger create/update/toggle/delete).

## Error codes (2026-11-15)

Every 400 streams answers is `bad_request` (validation and stream errors alike);
Python mixed `http_error` (bare HTTPException) and `bad_request`. One code per status
is the API cleanup's direction (errors.py: reuse the semantic subclasses); no client
reads `code`. Other statuses keep `http_error` until the cleanup pass.

## Review fixes (2026-11-15)

- Delivery: Autoclaim idle is `max(AGENTAREA_CHANNEL_AUTOCLAIM_IDLE, BatchSize * 2 targets * 30 s)` and takes at most BatchSize
  entries; each target is claimed (`sending:<event>:<target>`, 60 s) before the send, a claim held elsewhere leaves the
  message pending, a failure releases it.
- dlq-replay: dead letters carry `source_group`; a replay writes `target_group` and every other group of the source
  acknowledges the entry unprocessed (Bus and delivery). Entries dead-lettered before this change have no group and
  replay as before.
- `AGENTAREA_EVENT_RETENTION` under 1 day fails startup.
- Telegram live: a Redis lock per task serializes sends; a `tg:live:done:<task>` mark (1 h) makes later progress a no-op.
