"""The public webhook intake over the hermetic test session.

Intake finds the webhook's stream source, verifies and parses the request, and
puts one event on the stream's bus; firing the trigger is the router's job,
later. Ingest checks the stream and the quota in PostgreSQL and publishes to the
broker, so these tests stand a recording ingest in its place: what it records
is exactly what the real one would publish, keyed and deduplicated the same
way. ``fire`` then plays the router's part on a recorded event.
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
from agentarea_streams.domain.keys import event_id_for
from sqlalchemy.ext.asyncio import AsyncSession


class RecordingJournal:
    """Stands in for StreamIngest: one event per (stream, event_key), in order."""

    def __init__(self) -> None:
        self.events: list[tuple[UUID, IntegrationEvent, str]] = []
        self._seen: set[tuple[UUID, str]] = set()

    def bind(
        self, _session: AsyncSession, _context: Any, _settings: Any, _bus: Any
    ) -> "RecordingJournal":
        return self

    async def append(
        self,
        stream_id: UUID,
        event: IntegrationEvent,
        *,
        event_key: str,
        source_id: UUID | None = None,
        depth: int = 0,
        event_id: UUID | None = None,
    ) -> AppendResult:
        named = event_id or event_id_for(stream_id, event_key)
        if (stream_id, event_key) in self._seen:
            return AppendResult(event_id=named, appended=False)
        self.events.append((stream_id, event, event_key))
        self._seen.add((stream_id, event_key))
        return AppendResult(event_id=named, appended=True)

    def data(self, index: int = -1) -> dict[str, Any]:
        return self.events[index][1].data


class _NoSecrets:
    async def get_secret(self, name: str) -> str | None:
        return None


@pytest.fixture
def journal(monkeypatch) -> RecordingJournal:
    recorder = RecordingJournal()
    monkeypatch.setattr("agentarea_api.api.v1._webhook_intake.StreamIngest", recorder.bind)
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
        bus=None,  # type: ignore[arg-type]
        event_broker=None,
        settings=get_settings(),
    )
