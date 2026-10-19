import json
from datetime import datetime
from typing import Any
from uuid import UUID

from agentarea_common.events.ports import IntegrationEvent, UnprocessableEventError
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
    "source_type": "sourcetype",
    "session_key": "sessionkey",
    "sender": "sender",
}
_OPTIONAL_ATTRIBUTES = {"source_id", "source_type", "session_key", "sender"}
_ATTACHMENTS = "attachments"

#: The version of the event envelope (ADR-0040 §2) this code writes.
ENVELOPE_VERSION = 1


class Attachment(BaseModel):
    """A file of an event: ``ref`` is a workspace file path, or the provider's reference."""

    name: str
    mime: str | None = None
    size: int | None = None
    sha256: str | None = None
    ref: str
    #: True when ``ref`` is a workspace file; False for a provider reference.
    stored: bool = True


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
    #: The catalog entry of the source that brought it (ADR-0040 §2 envelope).
    source_type: str | None = None
    #: ``<source_id>:<value>``: the session a follow-up joins; None when the provider has none.
    session_key: str | None = None
    #: Whom sender admission checks; None when it does not apply.
    sender: str | None = None
    attachments: list[Attachment] = Field(default_factory=list)

    def to_bus(self) -> IntegrationEvent:
        extensions = dict(self.extensions)
        for field, name in _STREAM_ATTRIBUTES.items():
            value = getattr(self, field)
            if value is None:
                continue
            extensions[name] = value.isoformat() if isinstance(value, datetime) else str(value)
        if self.attachments:
            extensions[_ATTACHMENTS] = json.dumps(
                [a.model_dump(mode="json") for a in self.attachments], separators=(",", ":")
            )
        return IntegrationEvent(
            **self.model_dump(exclude={*_STREAM_ATTRIBUTES, "extensions", _ATTACHMENTS}),
            extensions=extensions,
        )

    @classmethod
    def from_bus(cls, event: IntegrationEvent) -> "StreamEvent":
        missing = [
            n
            for f, n in _STREAM_ATTRIBUTES.items()
            if f not in _OPTIONAL_ATTRIBUTES and n not in event.extensions
        ]
        if missing:
            raise ValueError(f"event {event.id} is not a stream event: no {', '.join(missing)}")
        own = {f: event.extensions.get(n) for f, n in _STREAM_ATTRIBUTES.items()}
        attachments = json.loads(event.extensions.get(_ATTACHMENTS) or "[]")
        taken = {*_STREAM_ATTRIBUTES.values(), _ATTACHMENTS}
        rest = {k: v for k, v in event.extensions.items() if k not in taken}
        return cls.model_validate(
            {
                **event.model_dump(exclude={"extensions"}),
                **own,
                "attachments": attachments,
                "extensions": rest,
            }
        )


def consumed_stream_event(message: IntegrationEvent) -> "StreamEvent":
    """The stream event a bus message carries; a message carrying none is dead-lettered at once."""
    try:
        return StreamEvent.from_bus(message)
    except Exception as error:
        raise UnprocessableEventError(f"not a stream event: {error}") from error


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


class TriggerBinding(BaseModel):
    """How a trigger is attached to the event journal, for the trigger API."""

    stream_id: UUID
    event_filter: dict[str, Any]
    last_event_at: datetime | None
