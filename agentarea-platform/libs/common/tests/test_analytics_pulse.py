"""When the pulse loop sends: only with the lock, only a day after the last pulse."""

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from agentarea_common.analytics import InstallationPulse, pulse

NOW = datetime(2030, 6, 15, 12, 0, 0)


class _Session:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


class _Sender:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.flushes = 0

    def enqueue(self, event: dict[str, Any]) -> None:
        self.events.append(event)

    async def flush(self) -> int:
        self.flushes += 1
        return len(self.events)


class _World:
    def __init__(self, monkeypatch, *, locked: bool, last_pulse_at: datetime | None) -> None:
        self.session = _Session()
        self.sender = _Sender()
        self.installation = SimpleNamespace(
            created_at=NOW - timedelta(days=10, hours=3), last_pulse_at=last_pulse_at
        )
        self.collected = 0

        async def try_lock(_session) -> bool:
            return locked

        async def installation(_session):
            return self.installation

        async def collect(_session, now):
            self.collected += 1
            return {"agents": {"total": 3}}

        monkeypatch.setattr(pulse, "try_pulse_lock", try_lock)
        monkeypatch.setattr(pulse, "get_or_create_installation", installation)
        monkeypatch.setattr(pulse, "collect_pulse", collect)

    @asynccontextmanager
    async def _factory(self):
        yield self.session

    def pulse(self) -> InstallationPulse:
        return InstallationPulse(
            session_factory=self._factory,  # type: ignore[arg-type]
            sender=self.sender,  # type: ignore[arg-type]
            clock=lambda: NOW,
        )


@pytest.mark.parametrize("last", [None, NOW - timedelta(hours=24), NOW - timedelta(days=9)])
async def test_a_due_pulse_is_sent_once_and_recorded(monkeypatch, last):
    world = _World(monkeypatch, locked=True, last_pulse_at=last)

    assert await world.pulse().run_once() is True

    assert world.sender.events == [
        {
            "event": "installation_pulse",
            "properties": {"install_age_days": 10, "agents": {"total": 3}},
        }
    ]
    assert world.sender.flushes == 1
    assert world.installation.last_pulse_at == NOW
    assert world.session.commits == 1


async def test_nothing_is_sent_within_a_day_of_the_last_pulse(monkeypatch):
    world = _World(monkeypatch, locked=True, last_pulse_at=NOW - timedelta(hours=23, minutes=59))

    assert await world.pulse().run_once() is False

    assert world.collected == 0
    assert world.sender.events == []
    assert world.session.commits == 0


async def test_a_replica_without_the_lock_sends_nothing(monkeypatch):
    world = _World(monkeypatch, locked=False, last_pulse_at=None)

    assert await world.pulse().run_once() is False

    assert world.collected == 0
    assert world.sender.events == []
    assert world.installation.last_pulse_at is None


async def test_a_failed_tick_is_logged_and_the_loop_goes_on(monkeypatch, caplog):
    world = _World(monkeypatch, locked=True, last_pulse_at=None)
    ticks = 0

    async def failing(_session, now):
        nonlocal ticks
        ticks += 1
        raise RuntimeError("database went away")

    monkeypatch.setattr(pulse, "collect_pulse", failing)
    loop = InstallationPulse(
        session_factory=world._factory,  # type: ignore[arg-type]
        sender=world.sender,  # type: ignore[arg-type]
        tick=timedelta(0),
        clock=lambda: NOW,
    )

    with caplog.at_level(logging.WARNING, logger="agentarea_common.analytics.pulse"):
        await loop.start()
        while ticks < 2:
            await pulse.asyncio.sleep(0)
        await loop.stop()

    assert caplog.records
    assert all(record.exc_info is not None for record in caplog.records)
    assert world.sender.events == []
