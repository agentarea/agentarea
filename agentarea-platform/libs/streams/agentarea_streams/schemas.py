"""Request DTOs shared by the REST routes and the streams toolset."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from .domain.filters import EventFilter


class StreamCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255, description="Name, unique in the workspace.")
    description: str = Field(default="", max_length=1000)
    retention_days: int | None = Field(
        default=None,
        ge=1,
        le=365,
        description="Days events are kept; omitted means the deployment's AGENTAREA_EVENT_RETENTION.",
    )


class SecretRef(BaseModel):
    """A workspace secret named instead of its value; the value stays where it is."""

    model_config = ConfigDict(extra="forbid")

    secret_id: UUID


class WebhookSourceCreate(BaseModel):
    """A webhook source on an existing stream, with no trigger."""

    model_config = ConfigDict(extra="forbid")

    webhook_type: str = Field(
        min_length=1, max_length=50, description="One of GET /streams/source-types."
    )
    credentials: dict[str, str | SecretRef] = Field(
        default_factory=dict,
        description=(
            "The type's credential fields, each a value or {secret_id} of a workspace "
            "secret. Write-only: never returned."
        ),
    )
    config: dict[str, str] = Field(
        default_factory=dict, description="The type's plain settings, e.g. shop_id."
    )


class ForwardCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    output_stream_ids: list[UUID] = Field(
        min_length=1, description="Streams every matching event is copied into; never the input."
    )
    event_filter: EventFilter = Field(
        default_factory=EventFilter, description="Which events are copied; empty copies all."
    )
