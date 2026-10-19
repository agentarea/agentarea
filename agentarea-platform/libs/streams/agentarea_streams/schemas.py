"""Request DTOs shared by the REST routes and the streams toolset."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from .domain.enums import SourceKind
from .domain.filters import EventFilter
from .domain.source_types import EventOverrides


class StreamCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255, description="Name, unique in the workspace.")
    description: str = Field(default="", max_length=1000)


class SecretRef(BaseModel):
    """A workspace secret named instead of its value; the value stays where it is."""

    model_config = ConfigDict(extra="forbid")

    secret_id: UUID


class SourceCreate(BaseModel):
    """A webhook or poll source of a catalog entry on an existing stream."""

    model_config = ConfigDict(extra="forbid")

    source_type: str = Field(
        min_length=1, max_length=50, description="A slug of GET /streams/source-types."
    )
    kind: SourceKind = Field(
        default=SourceKind.WEBHOOK,
        description="webhook: the provider posts to the source's URL; poll: the platform fetches.",
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
    event_templates: EventOverrides | None = Field(
        default=None,
        description=(
            "This source's own kind, key and session_key templates ({body:a.b}, "
            "{header:x}, {first_key:a|b}), in place of the type's. Without a key "
            "nothing is deduplicated."
        ),
    )


class ForwardCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    output_stream_ids: list[UUID] = Field(
        min_length=1, description="Streams every matching event is copied into; never the input."
    )
    event_filter: EventFilter = Field(
        default_factory=EventFilter, description="Which events are copied; empty copies all."
    )
