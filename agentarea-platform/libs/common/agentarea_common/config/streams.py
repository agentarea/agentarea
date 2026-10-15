"""Event settings: broker topic namespace and partitions, ingest quota, read model, the router."""

from datetime import timedelta

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .duration import Duration


class EventStreamSettings(BaseSettings):
    """Configuration for stream ingest, the events read model and the bus router."""

    model_config = SettingsConfigDict(env_prefix="AGENTAREA_EVENT_", extra="ignore")

    NAMESPACE: str = Field(
        default="agentarea",
        pattern=r"^[a-z][a-z0-9-]*$",
        description="First segment of every broker topic and key: <namespace>.<domain>.<dataset>.",
    )
    PARTITIONS: int = Field(
        default=16,
        ge=1,
        description="Partitions of the stream-events topic; a stream always maps to one of them.",
    )

    WRITE_QUOTA: int = Field(
        default=600, ge=1, description="Events one workspace may append per rolling minute."
    )
    RETENTION: Duration = Field(
        default=timedelta(days=7),
        description="Age past which whole daily partitions of the events read model are dropped.",
    )
    PARTITIONS_AHEAD: int = Field(
        default=7, ge=1, description="Daily read-model partitions kept created ahead of today."
    )
    FORWARD_DEPTH: int = Field(
        default=8, ge=1, description="Longest causation chain a forward may extend."
    )
    MAX_ATTEMPTS: int = Field(
        default=10,
        ge=1,
        description="Deliveries of one bus event before the router dead-letters it as an error.",
    )
