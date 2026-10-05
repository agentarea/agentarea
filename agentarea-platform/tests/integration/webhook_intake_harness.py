"""The public webhook intake over the hermetic test session.

Intake finds the webhook's stream source, verifies and parses the request, and
appends one event to the stream journal; firing the trigger is the dispatcher's
job, later. The journal's append is PostgreSQL (a global sequence, partitions,
ON CONFLICT), so these tests stand a recording journal in its place: what it
records is exactly what the real one would store, keyed and deduplicated the
same way. ``fire`` then plays the dispatcher's part on a recorded event.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

import pytest
from agentarea_api.api.v1._webhook_intake import WebhookSourceIntake
from agentarea_common.config import get_settings
from agentarea_common.events.ports import IntegrationEvent
from agentarea_streams.domain import AppendResult
from agentarea_streams.domain.ports import StreamWaker
from sqlalchemy.ext.asyncio import AsyncSession


class RecordingJournal:
    """Stands in for StreamJournal: one event per (stream, event_key), in order."""

    def __init__(self) -> None:
        self.events: list[tuple[UUID, IntegrationEvent, str]] = []
        self._sequences: dict[tuple[UUID, str], int] = {}

    def bind(self, _session: AsyncSession, _context: Any, _settings: Any) -> "RecordingJournal":
        return self

    async def append(
        self,
        stream_id: UUID,
        event: IntegrationEvent,
        *,
        event_key: str,
        source_id: UUID | None = None,
        depth: int = 0,
    ) -> AppendResult:
        known = self._sequences.get((stream_id, event_key))
        if known is not None:
            return AppendResult(sequence=known, appended=False)
        self.events.append((stream_id, event, event_key))
        sequence = len(self.events)
        self._sequences[(stream_id, event_key)] = sequence
        return AppendResult(sequence=sequence, appended=True)

    def data(self, index: int = -1) -> dict[str, Any]:
        return self.events[index][1].data


class RecordingWaker(StreamWaker):
    def __init__(self) -> None:
        self.woken: list[UUID] = []

    async def wake(self, stream_id: UUID) -> None:
        self.woken.append(stream_id)


class _NoSecrets:
    async def get_secret(self, name: str) -> str | None:
        return None


@pytest.fixture
def journal(monkeypatch) -> RecordingJournal:
    recorder = RecordingJournal()
    monkeypatch.setattr("agentarea_api.api.v1._webhook_intake.StreamJournal", recorder.bind)
    return recorder


@pytest.fixture
def intake(db_session, journal) -> WebhookSourceIntake:
    @asynccontextmanager
    async def same_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    return WebhookSourceIntake(
        lookup_session=db_session,
        session_scope=same_session,
        secret_reader_for=lambda _session, _context: _NoSecrets(),
        waker=RecordingWaker(),
        event_broker=None,
        settings=get_settings(),
    )
