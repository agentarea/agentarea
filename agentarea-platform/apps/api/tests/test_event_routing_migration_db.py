"""The event-routing migration marks every recorded event routed, with its reactions tallied.

An event with reactions is routed to the subscriptions that reacted, each
verdict counted; one without is routed to none. Set STREAMS_TEST_DATABASE_URL.
The statements run on temporary tables of the same names, so the migrated
tables are untouched.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

TEST_DATABASE_URL = os.getenv("STREAMS_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="STREAMS_TEST_DATABASE_URL not set")

MIGRATION = Path(__file__).resolve().parents[1] / "alembic/versions/20261019_1000_event_routing.py"


def _migration():
    spec = importlib.util.spec_from_file_location("_event_routing", MIGRATION)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_recorded_events_are_routed_to_the_subscriptions_that_reacted() -> None:
    module = _migration()
    ws, stream = "w", uuid4()
    reacted_to, unheard = uuid4(), uuid4()
    engine = create_async_engine(TEST_DATABASE_URL)
    try:
        async with engine.connect() as conn:
            await conn.execute(
                text(
                    "CREATE TEMP TABLE stream_events (workspace_id text, stream_id uuid, "
                    "event_id uuid, received_at timestamptz, routed_at timestamptz, "
                    "subscribers int, reacted int NOT NULL DEFAULT 0, "
                    "skipped int NOT NULL DEFAULT 0, errors int NOT NULL DEFAULT 0)"
                )
            )
            await conn.execute(
                text(
                    "CREATE TEMP TABLE trigger_executions (workspace_id text, stream_id uuid, "
                    "event_id uuid, subscription_id uuid, verdict text)"
                )
            )
            for event in (reacted_to, unheard):
                await conn.execute(
                    text(
                        "INSERT INTO stream_events (workspace_id, stream_id, event_id, "
                        "received_at) VALUES (:w, :s, :e, now())"
                    ),
                    {"w": ws, "s": stream, "e": event},
                )
            for verdict in ("reacted", "skipped", "error"):
                await conn.execute(
                    text("INSERT INTO trigger_executions VALUES (:w, :s, :e, :sub, :v)"),
                    {"w": ws, "s": stream, "e": reacted_to, "sub": uuid4(), "v": verdict},
                )
            await conn.execute(
                text("INSERT INTO trigger_executions VALUES (:w, :s, :e, NULL, 'reacted')"),
                {"w": ws, "s": stream, "e": reacted_to},
            )
            await conn.execute(text(module.BACKFILL))
            await conn.execute(text(module.UNREACHED))
            rows = (
                await conn.execute(
                    text(
                        "SELECT event_id, routed_at = received_at, subscribers, reacted, "
                        "skipped, errors FROM stream_events"
                    )
                )
            ).all()
            await conn.rollback()
    finally:
        await engine.dispose()

    assert {row[0]: tuple(row[1:]) for row in rows} == {
        reacted_to: (True, 3, 3, 1, 1),
        unheard: (True, 0, 0, 0, 0),
    }
