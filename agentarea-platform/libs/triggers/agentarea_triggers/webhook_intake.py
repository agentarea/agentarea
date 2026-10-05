"""Webhook intake into a stream: the parsed request becomes one journal event."""

from typing import Any
from uuid import UUID, uuid4

from agentarea_common.events.ports import IntegrationEvent
from agentarea_streams.domain import AppendResult, StreamError, WebhookSourceSpec
from agentarea_streams.infrastructure.journal import StreamJournal
from agentarea_streams.infrastructure.orm import StreamSourceORM

from .webhook_manager import WebhookExecutionCallback

_DELIVERY_HEADERS = ("webhook-id", "x-github-delivery", "linear-delivery", "idempotency-key")
_BODY_KEYS = {"telegram": "update_id", "stripe": "id", "slack": "event_id", "discord": "id"}
_HIDDEN_HEADERS = frozenset(
    {
        "authorization",
        "proxy-authorization",
        "cookie",
        "x-api-key",
        "x-webhook-secret",
        "x-telegram-bot-api-secret-token",
    }
)


def webhook_event_key(webhook_type: str, parsed: dict[str, Any]) -> str:
    """The provider's own delivery id, or a fresh key: such an event is never a repeat."""
    headers = {str(k).lower(): v for k, v in (parsed.get("headers") or {}).items()}
    for header in _DELIVERY_HEADERS:
        if headers.get(header):
            return f"{header}:{headers[header]}"
    body_key = _BODY_KEYS.get(webhook_type)
    raw = parsed.get("raw_data")
    if body_key and isinstance(raw, dict) and raw.get(body_key) is not None:
        return f"{webhook_type}:{raw[body_key]}"
    return f"recv:{uuid4()}"


def webhook_event_kind(webhook_type: str, parsed: dict[str, Any]) -> str:
    event_type = parsed.get("event_type")
    return str(event_type) if event_type else f"webhook.{webhook_type}"


def journal_data(parsed: dict[str, Any]) -> dict[str, Any]:
    headers = parsed.get("headers") or {}
    return {
        **parsed,
        "headers": {k: v for k, v in headers.items() if str(k).lower() not in _HIDDEN_HEADERS},
    }


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
        self.refusal: StreamError | None = None

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
        return {"status": "accepted" if self.receipt.appended else "duplicate"}
