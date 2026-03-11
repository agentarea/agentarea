# Event Channels: Bidirectional Multi-Channel Agent Communication

**Date:** 2026-03-11
**Status:** Draft
**Branch:** TBD (new branch from main)

## Problem

AgentArea agents currently only communicate through the webUI. Users want to message agents via Telegram, email, and other channels — and get responses back in the same channel. External systems (Linear, GitHub) should also trigger agent work.

The webUI is already an event channel — we just haven't generalized the pattern.

## Industry Context

No agentic platform has solved bidirectional multi-channel well:

| System | Inbound | Outbound | Bidirectional |
|--------|---------|----------|---------------|
| Temporal Ambient Agents | Signals (durable) | Activities (custom) | Manual per channel |
| AG-UI Protocol | SSE + HTTP POST | SSE stream | Web UI only |
| CrewAI Flows | `kickoff()` call | No adapters | No |
| OpenAI Agents SDK | Stateless invocation | Stream events | No persistence |
| Novu/Knock | N/A | Templates + delivery | Outbound only |

The opportunity: build the bidirectional channel layer that the industry is missing, on top of Temporal's durable execution.

## Core Concept

**Channel = inbound events + outbound responses + presentation policy**

```
               ┌─────────────────────────────┐
               │     Agent Execution          │
               │     (Temporal Workflow)       │
               └──────────┬──────────────────┘
                          │ events
                          ▼
┌──────────┐    ┌─────────────────────┐    ┌──────────────┐
│ Inbound  │───▶│   Event Pipeline    │───▶│  Outbound    │
│ Adapters │    │   (Redis pub/sub)   │    │  Router      │
└──────────┘    │   (DB persistence)  │    └──────┬───────┘
                └─────────────────────┘           │
                                                  ▼
                                         ┌────────────────┐
                                         │ Channel Adapter │
                                         │ + Presentation  │
                                         └────────────────┘
```

Three transport types, one abstraction:

| Transport | Inbound mechanism | Examples |
|-----------|-------------------|----------|
| **Webhook** (push) | HTTP callback | Telegram, Slack, WhatsApp, GitHub, Linear, Jira |
| **Poll** (pull) | Cron + fetch | IMAP email, MailSlurper, RSS, REST API polling |
| **Stream** (continuous) | Long-running consumer | Kafka, Redis Streams (future) |

## What Already Exists

- **Webhook triggers** with parsers for: Telegram, Slack, GitHub, Discord, Linear, Stripe, Generic
- **Cron triggers** with Temporal schedules
- **Event pipeline**: workflow events → Redis pub/sub + DB persistence → SSE to webUI
- **Task creation** from triggers with `task_parameters`

## What's Missing

1. **Channel metadata on tasks** — "this came from Telegram chat 12345, respond there"
2. **Outbound routing** — when agent completes, send result back to originating channel
3. **Presentation filtering** — what events to surface per channel
4. **Poll-based inbound** — email fetching (IMAP, MailSlurper)
5. **More webhook parsers** — WhatsApp, Jira, Notion

## Design

### 1. Channel Origin (on tasks)

No new models. Use existing `task_parameters`:

```python
task_parameters = {
    # Existing fields...
    "channel_origin": {
        "type": "telegram",          # channel type
        "chat_id": "12345",          # where to respond
        "message_id": "678",         # correlation to original message
        "user_display_name": "John", # for logging/display
        "presentation": "concise",   # what to show back
    }
}
```

When a trigger creates a task, it includes `channel_origin`. The trigger already knows the source (it parsed the webhook). This is just threading that info through.

WebUI tasks have no `channel_origin` — they use existing SSE (backward compatible, zero changes to webUI).

### 2. Event Visibility Categories

Group existing event types by audience:

```python
class EventVisibility:
    # Final answer, errors — always shown
    RESULT = {"WorkflowCompleted", "WorkflowFailed"}

    # Agent needs human input — shown on interactive channels
    INTERACTION = {"HumanApprovalRequested", "HumanApprovalReceived"}

    # Progress indicators — shown on concise channels
    STATUS = {
        "IterationStarted", "ToolCallStarted",
        "AgentDelegationStarted", "AgentDelegationCompleted",
    }

    # Full detail — only webUI
    INTERNAL = {
        "LLMCallChunk", "LLMCallCompleted",
        "ToolCallCompleted", "ContextCompacted",
        "BudgetWarning",
    }
```

Presentation modes:

| Mode | Shows | Use case |
|------|-------|----------|
| `verbose` | Everything | WebUI (existing SSE) |
| `concise` | result + interaction + status | Telegram, Slack |
| `summary` | result + interaction | Email (batched at end) |
| `silent` | result only | System-to-system |

### 3. Outbound Channel Router

A service that subscribes to the existing Redis pub/sub event stream and routes to external channels:

```python
class ChannelRouter:
    """Subscribes to task events, routes to external channels."""

    def __init__(self, adapters: dict[str, ChannelAdapter]):
        self.adapters = adapters

    async def on_task_event(self, event: TaskEvent):
        # Get task's channel origin
        task = await self.task_service.get(event.task_id)
        channel = task.task_parameters.get("channel_origin")
        if not channel:
            return  # webUI handles itself

        # Check visibility
        presentation = channel.get("presentation", "concise")
        if not is_visible(event.event_type, presentation):
            return

        # Format and send
        adapter = self.adapters.get(channel["type"])
        if adapter:
            message = adapter.format(event, presentation)
            await adapter.send(channel, message)
```

This runs as a standalone worker process (or a Temporal workflow).

### 4. Channel Adapter Protocol

```python
class ChannelAdapter(Protocol):
    """Bidirectional channel adapter."""

    def format(self, event: TaskEvent, presentation: str) -> str:
        """Format an event for this channel."""
        ...

    async def send(self, channel_config: dict, message: str) -> None:
        """Send a message to this channel."""
        ...
```

### 5. Concrete Adapters

#### Telegram Adapter
- **Inbound**: Webhook trigger (parser already exists)
- **Outbound**: Bot API `sendMessage`
- **Format**: Plain text with minimal markdown
- **Threading**: Reply to original `message_id`

#### Email Adapter
- **Inbound**: Cron trigger + IMAP/MailSlurper poll
- **Outbound**: SMTP send
- **Format**: HTML email with summary
- **Threading**: Reply with `In-Reply-To` header for email threading
- **Presentation**: `summary` mode — batch all events, send one email when done

#### Slack Adapter
- **Inbound**: Webhook trigger (parser already exists)
- **Outbound**: Slack Web API `chat.postMessage`
- **Format**: Block Kit for rich formatting
- **Threading**: Reply in thread via `thread_ts`

#### WebUI Adapter (implicit)
- **Inbound**: API → task creation (existing)
- **Outbound**: SSE stream (existing)
- **Format**: Full event stream with markdown
- **No changes needed** — this is the existing behavior

### 6. Poll-Based Inbound (Data Extractors)

For channels that don't push (email), add to CronTrigger:

```python
class CronTrigger(Trigger):
    trigger_type: TriggerType = TriggerType.CRON
    cron_expression: str
    timezone: str = "UTC"
    # Remove: next_run_time (Temporal handles scheduling)

    # Data extraction for poll-based channels
    data_extractor: str | None = None          # "mailslurper", "imap", etc.
    data_extractor_config: dict | None = None  # Connection details
    data_extractor_state: dict | None = None   # Cursor/last-seen tracking
```

Extractor protocol:

```python
class DataExtractor(Protocol):
    async def extract(
        self, config: dict, state: dict | None
    ) -> ExtractionResult:
        ...

@dataclass
class ExtractionResult:
    has_new_data: bool
    events: list[dict]       # Normalized events
    updated_state: dict      # New cursor/checkpoint
    channel_origin: dict     # Pre-built channel_origin for task creation
```

The trigger execution workflow becomes:

```
cron fires
  → extractor.extract(config, state)
  → has_new_data?
    → yes: create task with extracted_data + channel_origin
    → no: record "skipped", update state, done
```

### 7. Trigger Execution Flow Update

```python
# In TriggerExecutionWorkflow:

# 1. Run data extractor if configured
if trigger.data_extractor:
    result = await extract_data_activity(trigger)
    if not result.has_new_data:
        return {"status": "skipped", "reason": "no_new_data"}
    execution_data["extracted_data"] = result.events
    execution_data["channel_origin"] = result.channel_origin

# 2. For webhook triggers, build channel_origin from parsed webhook data
elif trigger.trigger_type == TriggerType.WEBHOOK:
    execution_data["channel_origin"] = build_channel_origin(trigger, webhook_data)

# 3. Create task with channel_origin in task_parameters
task = create_task(
    task_parameters={
        **trigger.task_parameters,
        "channel_origin": execution_data.get("channel_origin"),
    }
)
```

## Critique and Risks

### What could go wrong

1. **Message ordering in Telegram** — If agent sends multiple status updates, they may arrive out of order. Mitigation: rate-limit outbound messages, batch status updates with short delay.

2. **Email reply parsing is hard** — Quoted text, signatures, forwarded content. The IMAP extractor needs to strip these. This is a known hard problem. Start with MailSlurper (clean messages), tackle IMAP reply parsing later.

3. **Channel Router as SPOF** — If the router crashes, outbound messages are lost. Mitigation: the events are already persisted in DB. Router can replay missed events on restart by checking last-delivered event per task.

4. **Presentation mode isn't enough** — "concise" may still be too noisy for some users. May need per-user channel preferences later. Good enough for now.

5. **Cost of outbound API calls** — Telegram Bot API, Slack API, SMTP — all have rate limits. Need to respect them. The router should have per-channel rate limiting.

6. **Security** — Webhook validation (Telegram uses a secret token, Slack uses signing secrets). Already partially handled in webhook_manager.py but needs hardening for production.

### What we're NOT building (yet)

- **Kafka/Redis stream consumers** — Design accommodates them, but no concrete need now
- **Conversational state across channels** — Same user messaging on Telegram AND email. Out of scope.
- **Rich media** — Images, files, voice messages. Text only for now.
- **Channel preferences per user** — "I prefer Telegram for urgent, email for summaries". Future.
- **Outbound-only notifications** — "Alert me on Slack when any agent fails". This is a notification rule engine, separate from channel responses. Future.

## Implementation Order

1. **Channel origin + event visibility** — Data model changes, no new infra
2. **Remove `next_run_time` from CronTrigger** — Cleanup
3. **Add `data_extractor` fields to CronTrigger** — Model + ORM + migration
4. **MailSlurper extractor** — First poll-based channel
5. **Channel Router service** — Redis subscriber + dispatch
6. **Telegram adapter (outbound)** — Bot API send + format
7. **Email adapter (outbound)** — SMTP send
8. **IMAP extractor** — Production email inbound
9. **More webhook parsers** — WhatsApp, Jira, Notion (as needed)

## Files to Modify

| File | Change |
|------|--------|
| `libs/triggers/domain/models.py` | Remove `next_run_time`, add extractor fields |
| `libs/triggers/infrastructure/orm.py` | Column changes |
| `libs/triggers/infrastructure/repository.py` | Update mappings |
| `libs/triggers/trigger_service.py` | Handle extractors in execution |
| `libs/execution/workflows/constants.py` | Event visibility categories |

## Files to Create

| File | Purpose |
|------|---------|
| `libs/triggers/extractors/__init__.py` | DataExtractor protocol + registry |
| `libs/triggers/extractors/mailslurper.py` | MailSlurper email extraction |
| `libs/triggers/extractors/imap.py` | IMAP email extraction |
| `libs/channels/__init__.py` | ChannelAdapter protocol |
| `libs/channels/router.py` | ChannelRouter (Redis subscriber) |
| `libs/channels/adapters/telegram.py` | Telegram Bot API adapter |
| `libs/channels/adapters/email.py` | SMTP outbound adapter |
| `libs/channels/adapters/slack.py` | Slack Web API adapter |
| `libs/channels/visibility.py` | Event visibility filtering |

## Dependencies

- `aiogram` or `python-telegram-bot` for Telegram Bot API
- `aiosmtplib` for async SMTP
- `aioimaplib` for async IMAP
- No new infrastructure — uses existing Redis pub/sub + DB
