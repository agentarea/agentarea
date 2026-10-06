"""Event stream settings: journal quota, retention, partitions, dispatch."""

from datetime import timedelta

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .duration import Duration


class EventStreamSettings(BaseSettings):
    """Configuration for stream journals and the subscription dispatcher."""

    model_config = SettingsConfigDict(env_prefix="AGENTAREA_EVENT_", extra="ignore")

    WRITE_QUOTA: int = Field(
        default=600, ge=1, description="Events one workspace may append per rolling minute."
    )
    RETENTION: Duration = Field(
        default=timedelta(days=30),
        description="Age past which whole daily journal partitions are dropped.",
    )
    PARTITIONS_AHEAD: int = Field(
        default=7, ge=1, description="Daily journal partitions kept created ahead of today."
    )
    DISPATCH_EVERY: Duration = Field(
        default=timedelta(seconds=2),
        description="Dispatcher poll interval when no wake signal arrives.",
    )
    DISPATCH_BATCH: int = Field(
        default=50, ge=1, description="Events one subscription handles per lease."
    )
    FORWARD_DEPTH: int = Field(
        default=8, ge=1, description="Longest causation chain a forward may extend."
    )
    MAX_ATTEMPTS: int = Field(
        default=10, ge=1, description="Retries of one event before its outcome is an error."
    )
    LEASE: Duration = Field(
        default=timedelta(minutes=5),
        description="How long a dispatcher holds a subscription before another may take it.",
    )
