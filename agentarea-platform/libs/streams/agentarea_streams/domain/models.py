from datetime import datetime
from typing import Any
from uuid import UUID

from agentarea_common.events.ports import IntegrationEvent
from pydantic import BaseModel, Field

from .enums import SubscriptionKind, Verdict
from .filters import EventFilter

_STREAM_ATTRIBUTES = {
    "stream_id": "streamid",
    "workspace_id": "workspaceid",
    "created_by": "createdby",
    "event_key": "eventkey",
    "received_at": "receivedat",
    "depth": "depth",
    "source_id": "sourceid",
}


class StreamEvent(IntegrationEvent):
    """An event of one stream, as the bus carries it on its ``streams.events`` partition.

    ``id`` is deterministic (``uuid5(stream, event_key)``, or the processor's
    derived id), so every repeat of the event names the same one. The stream
    attributes travel as CloudEvents extensions.
    """

    stream_id: UUID
    workspace_id: str
    created_by: str
    event_key: str
    received_at: datetime
    depth: int = 0
    source_id: UUID | None = None

    def to_bus(self) -> IntegrationEvent:
        extensions = dict(self.extensions)
        for field, name in _STREAM_ATTRIBUTES.items():
            value = getattr(self, field)
            if value is None:
                continue
            extensions[name] = value.isoformat() if isinstance(value, datetime) else str(value)
        return IntegrationEvent(
            **self.model_dump(exclude={*_STREAM_ATTRIBUTES, "extensions"}),
            extensions=extensions,
        )

    @classmethod
    def from_bus(cls, event: IntegrationEvent) -> "StreamEvent":
        missing = [
            n
            for f, n in _STREAM_ATTRIBUTES.items()
            if f != "source_id" and n not in event.extensions
        ]
        if missing:
            raise ValueError(f"event {event.id} is not a stream event: no {', '.join(missing)}")
        own = {f: event.extensions.get(n) for f, n in _STREAM_ATTRIBUTES.items()}
        rest = {k: v for k, v in event.extensions.items() if k not in _STREAM_ATTRIBUTES.values()}
        return cls.model_validate(
            {**event.model_dump(exclude={"extensions"}), **own, "extensions": rest}
        )


class RecordedEvent(StreamEvent):
    """A stream event as the events read model holds it, with its position there."""

    sequence: int


class AppendResult(BaseModel):
    event_id: UUID
    appended: bool


class HandlerResult(BaseModel):
    verdict: Verdict
    reason: str | None = None
    score: float | None = None
    task_id: UUID | None = None
    derived_event_ids: list[UUID] = Field(default_factory=list)


class SubscriptionView(BaseModel):
    """What a handler needs to know about the subscription it serves."""

    id: UUID
    workspace_id: str
    created_by: str
    stream_id: UUID
    kind: SubscriptionKind
    trigger_id: UUID | None
    filter: EventFilter
    output_stream_ids: list[UUID]


class WebhookSourceSpec(BaseModel):
    """A webhook source as the intake reads it; duck-types the trigger fields intake needs."""

    id: UUID
    stream_id: UUID
    workspace_id: str
    created_by: str
    webhook_id: str
    webhook_type: str
    allowed_methods: list[str]
    validation_rules: dict[str, Any]
    webhook_config: dict[str, Any] | None
    credential_key: UUID
    event_types: list[str] = Field(default_factory=list)
    is_active: bool = True


class TriggerBinding(BaseModel):
    """How a trigger is attached to the event journal, for the trigger API."""

    stream_id: UUID
    event_filter: dict[str, Any]
    webhook_id: str | None
    last_event_at: datetime | None
