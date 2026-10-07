"""Webhook intake into a stream: the parsed request becomes one journal event."""

import logging
from typing import Any
from uuid import UUID, uuid4

from agentarea_common.events.ports import IntegrationEvent
from agentarea_streams.domain import AppendResult, StreamError, WebhookSourceSpec
from agentarea_streams.infrastructure.journal_repository import StreamJournal
from agentarea_streams.infrastructure.orm import StreamSourceORM

from .event_scrub import journal_data
from .webhook_manager import WebhookExecutionCallback

logger = logging.getLogger(__name__)

_DELIVERY_HEADERS = ("webhook-id", "x-github-delivery", "linear-delivery", "idempotency-key")
_TYPE_DELIVERY_HEADERS = {"sentry": "request-id"}
_BODY_KEYS = {"telegram": "update_id", "stripe": "id", "slack": "event_id", "discord": "id"}


def _yookassa_key(raw: dict[str, Any]) -> str | None:
    """A notification is one object reaching one state: both name it."""
    obj = raw.get("object")
    object_id = obj.get("id") if isinstance(obj, dict) else None
    event = raw.get("event")
    return f"yookassa:{event}:{object_id}" if event and object_id else None


def webhook_event_key(webhook_type: str, parsed: dict[str, Any]) -> str:
    """The provider's own delivery id, or a fresh key: such an event is never a repeat."""
    headers = {str(k).lower(): v for k, v in (parsed.get("headers") or {}).items()}
    type_header = _TYPE_DELIVERY_HEADERS.get(webhook_type)
    for header in (*_DELIVERY_HEADERS, *([type_header] if type_header else [])):
        if headers.get(header):
            return f"{header}:{headers[header]}"
    raw = parsed.get("raw_data")
    if webhook_type == "yookassa" and isinstance(raw, dict) and (key := _yookassa_key(raw)):
        return key
    body_key = _BODY_KEYS.get(webhook_type)
    if body_key and isinstance(raw, dict) and raw.get(body_key) is not None:
        return f"{webhook_type}:{raw[body_key]}"
    return f"recv:{uuid4()}"


def webhook_event_kind(webhook_type: str, parsed: dict[str, Any]) -> str:
    event_type = parsed.get("event_type")
    return str(event_type) if event_type else f"webhook.{webhook_type}"


def spec_from_source(source: StreamSourceORM) -> WebhookSourceSpec:
    if not (source.webhook_id and source.webhook_type and source.credential_key):
        raise ValueError(f"stream source {source.id} is not a complete webhook source")
    return WebhookSourceSpec(
        # Signature secrets are stored under channel_cred:{type}:{credential_key};
        # intake passes spec.id where it used to pass the trigger id.
        id=source.credential_key,
        stream_id=source.stream_id,
        workspace_id=source.workspace_id,
        created_by=source.created_by,
        webhook_id=source.webhook_id,
        webhook_type=source.webhook_type,
        allowed_methods=list(source.allowed_methods or []),
        validation_rules=dict(source.validation_rules or {}),
        webhook_config=source.webhook_config,
        credential_key=source.credential_key,
    )


class JournalAppendCallback(WebhookExecutionCallback):
    """Records the verified, parsed request instead of running a trigger."""

    def __init__(self, *, journal: StreamJournal, spec: WebhookSourceSpec, source_id: UUID):
        self.journal = journal
        self.spec = spec
        self.source_id = source_id
        self.receipt: AppendResult | None = None
        # The journal refused the event: the sender's problem, answered 4xx.
        self.refusal: StreamError | None = None
        # The journal could not take the event: ours, answered 5xx so the sender retries.
        self.failure: Exception | None = None

    async def execute_webhook_trigger(
        self, webhook_id: str, request_data: dict[str, Any]
    ) -> object:
        event = IntegrationEvent(
            type=webhook_event_kind(self.spec.webhook_type, request_data),
            source=f"webhook:{self.spec.webhook_type}",
            subject=webhook_id,
            data=journal_data(request_data),
        )
        try:
            self.receipt = await self.journal.append(
                self.spec.stream_id,
                event,
                event_key=webhook_event_key(self.spec.webhook_type, request_data),
                source_id=self.source_id,
            )
        except StreamError as error:
            self.refusal = error
            raise
        except Exception as error:
            logger.error(
                "Webhook %s could not be recorded in stream %s",
                webhook_id,
                self.spec.stream_id,
                exc_info=True,
            )
            self.failure = error
            raise
        return {"status": "accepted" if self.receipt.appended else "duplicate"}
