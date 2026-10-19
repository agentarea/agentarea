"""The workspace feed: every event of the streams a caller may read, newest first."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from .models import RecordedEvent
from .processing import Processing, ProcessingStatus, processing_status

_WILDCARD = ".*"


class FeedFilter(BaseModel):
    stream_id: UUID | None = None
    source_type: str | None = None
    #: ``order.paid``, or ``order.*`` for every kind under ``order.``.
    kind: str | None = None
    sender: str | None = None
    session_key: str | None = None
    result: ProcessingStatus | None = None
    since: datetime | None = None
    until: datetime | None = None
    event_id: UUID | None = None
    #: False leaves out the platform's own events (source type ``platform``).
    platform: bool = True

    def kind_prefix(self) -> str | None:
        if self.kind is None or not self.kind.endswith(_WILDCARD):
            return None
        return self.kind[: -len(_WILDCARD) + 1]

    def exact_kind(self) -> str | None:
        if self.kind is None or self.kind.endswith(_WILDCARD):
            return None
        return self.kind


class RoutedEvent(RecordedEvent):
    """A recorded event with what the router did with it."""

    routed_at: datetime | None
    subscribers: int | None
    reacted: int
    skipped: int
    errors: int

    def processing(self) -> Processing:
        return Processing(
            status=processing_status(
                routed=self.routed_at is not None,
                subscribers=self.subscribers,
                reacted=self.reacted,
                skipped=self.skipped,
                errors=self.errors,
            ),
            subscribers=self.subscribers,
            reacted=self.reacted,
            skipped=self.skipped,
            errors=self.errors,
        )


class FeedFacets(BaseModel):
    """How many events of the filtered feed each stream and each source type holds."""

    streams: dict[UUID, int]
    source_types: dict[str, int]
