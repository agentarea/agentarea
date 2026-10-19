"""What the platform did with an event: its routing and the reactions recorded since.

The router writes when it matched an event and to how many subscriptions; each
subscription's reaction is a recorded verdict. The status follows from both.
"""

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field


class ProcessingStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    HANDLED = "handled"
    ERROR = "error"
    NO_HANDLERS = "no_handlers"
    SKIPPED = "skipped"


class ProcessingTask(BaseModel):
    id: UUID
    status: str


class Processing(BaseModel):
    status: ProcessingStatus
    subscribers: int | None = Field(
        description="Subscriptions the router matched; null until it routed the event."
    )
    reacted: int = Field(description="Subscriptions whose reaction is recorded.")
    skipped: int
    errors: int
    tasks: list[ProcessingTask] = Field(default_factory=list)


def processing_status(
    *, routed: bool, subscribers: int | None, reacted: int, skipped: int, errors: int
) -> ProcessingStatus:
    if not routed:
        return ProcessingStatus.QUEUED
    if subscribers is None:
        raise ValueError("a routed event names its subscribers")
    # A subscription paused at routing and resumed before a redelivery reacts
    # without having been counted.
    expected = max(subscribers, reacted)
    if expected == 0:
        return ProcessingStatus.NO_HANDLERS
    if errors:
        return ProcessingStatus.ERROR
    if reacted < expected:
        return ProcessingStatus.PROCESSING
    if skipped == reacted:
        return ProcessingStatus.SKIPPED
    return ProcessingStatus.HANDLED
