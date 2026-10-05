from datetime import datetime
from typing import Any
from uuid import UUID

from agentarea_common.events.ports import IntegrationEvent
from pydantic import BaseModel, Field

from .enums import SubscriptionKind, Verdict
from .filters import EventFilter


class JournaledEvent(IntegrationEvent):
    """An IntegrationEvent as the journal stored it, with its cursor position."""

    stream_id: UUID
    sequence: int
    event_key: str
    received_at: datetime
    depth: int = 0


class AppendResult(BaseModel):
    sequence: int
    appended: bool


class HandlerResult(BaseModel):
    verdict: Verdict
    reason: str | None = None
    score: float | None = None
    task_id: UUID | None = None
    derived_sequences: list[int] = Field(default_factory=list)


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
