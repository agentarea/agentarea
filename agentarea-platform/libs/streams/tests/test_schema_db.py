"""The migrated stream schema: partitioning, dedup keys, one trigger per subscription.

Set STREAMS_TEST_DATABASE_URL to a postgresql+asyncpg URL of a disposable,
already-migrated database (scripts/check-db.sh does).
"""

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.getenv("STREAMS_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="STREAMS_TEST_DATABASE_URL not set")


@pytest.fixture
async def session():
    engine = create_async_engine(TEST_DATABASE_URL)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


async def test_stream_events_is_range_partitioned_by_day(session):
    partitioned = await session.execute(
        text(
            "SELECT count(*) FROM pg_partitioned_table p JOIN pg_class c ON c.oid = p.partrelid "
            "WHERE c.relname = 'stream_events' AND p.partstrat = 'r'"
        )
    )
    assert partitioned.scalar_one() == 1
    today = datetime.now(UTC).date()
    for offset in (0, 7):
        name = f"stream_events_p{(today + timedelta(days=offset)):%Y%m%d}"
        found = await session.execute(text("SELECT to_regclass(:n) IS NOT NULL"), {"n": name})
        assert found.scalar_one(), name


async def test_a_webhook_id_belongs_to_one_source(session):
    ws, stream_id = str(uuid4()), uuid4()
    await session.execute(
        text(
            "INSERT INTO streams (id, workspace_id, created_by, name, description, kind, "
            "retention_days, created_at, updated_at) VALUES (:id, :ws, 'u', 'n', '', 'custom', 30, "
            "now(), now())"
        ),
        {"id": stream_id, "ws": ws},
    )
    insert_source = text(
        "INSERT INTO stream_sources (id, workspace_id, created_by, stream_id, kind, webhook_id, "
        "webhook_type, allowed_methods, validation_rules, credential_key, created_at, updated_at) "
        "VALUES (:id, :ws, 'u', :stream, 'webhook', 'same-webhook-id-0001', 'generic', "
        "'[\"POST\"]', '{}', :key, now(), now())"
    )
    await session.execute(insert_source, {"id": uuid4(), "ws": ws, "stream": stream_id, "key": uuid4()})
    with pytest.raises(IntegrityError):
        await session.execute(
            insert_source, {"id": uuid4(), "ws": ws, "stream": stream_id, "key": uuid4()}
        )


async def test_a_trigger_subscription_must_name_its_trigger(session):
    ws, stream_id = str(uuid4()), uuid4()
    await session.execute(
        text(
            "INSERT INTO streams (id, workspace_id, created_by, name, description, kind, "
            "retention_days, created_at, updated_at) VALUES (:id, :ws, 'u', 'n2', '', 'custom', 30, "
            "now(), now())"
        ),
        {"id": stream_id, "ws": ws},
    )
    with pytest.raises(IntegrityError, match="ck_stream_subscriptions_trigger"):
        await session.execute(
            text(
                "INSERT INTO stream_subscriptions (id, workspace_id, created_by, stream_id, kind, "
                "filter, output_stream_ids, cursor_sequence, status, attempts, created_at, "
                "updated_at) VALUES (:id, :ws, 'u', :s, 'trigger', '{}', '[]', 0, 'active', 0, "
                "now(), now())"
            ),
            {"id": uuid4(), "ws": ws, "s": stream_id},
        )
