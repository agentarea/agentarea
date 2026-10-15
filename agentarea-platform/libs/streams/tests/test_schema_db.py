"""The migrated stream schema: partitioning, one row per event, one trigger per subscription.

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
            "created_at, updated_at) VALUES (:id, :ws, 'u', 'n', '', 'custom', now(), now())"
        ),
        {"id": stream_id, "ws": ws},
    )
    insert_source = text(
        "INSERT INTO stream_sources (id, workspace_id, created_by, stream_id, kind, webhook_id, "
        "webhook_type, allowed_methods, validation_rules, credential_key, created_at, updated_at) "
        "VALUES (:id, :ws, 'u', :stream, 'webhook', 'same-webhook-id-0001', 'generic', "
        "'[\"POST\"]', '{}', :key, now(), now())"
    )
    await session.execute(
        insert_source, {"id": uuid4(), "ws": ws, "stream": stream_id, "key": uuid4()}
    )
    with pytest.raises(IntegrityError):
        await session.execute(
            insert_source, {"id": uuid4(), "ws": ws, "stream": stream_id, "key": uuid4()}
        )


async def test_a_trigger_subscription_must_name_its_trigger(session):
    ws, stream_id = str(uuid4()), uuid4()
    await session.execute(
        text(
            "INSERT INTO streams (id, workspace_id, created_by, name, description, kind, "
            "created_at, updated_at) VALUES (:id, :ws, 'u', 'n2', '', 'custom', now(), now())"
        ),
        {"id": stream_id, "ws": ws},
    )
    with pytest.raises(IntegrityError, match="ck_stream_subscriptions_trigger"):
        await session.execute(
            text(
                "INSERT INTO stream_subscriptions (id, workspace_id, created_by, stream_id, kind, "
                "filter, output_stream_ids, status, created_at, updated_at) VALUES (:id, :ws, "
                "'u', :s, 'trigger', '{}', '[]', 'active', now(), now())"
            ),
            {"id": uuid4(), "ws": ws, "s": stream_id},
        )


async def test_the_journal_and_dispatcher_tables_and_columns_are_gone(session):
    for table in ("stream_event_keys", "subscription_outcomes"):
        found = await session.execute(text("SELECT to_regclass(:t) IS NOT NULL"), {"t": table})
        assert not found.scalar_one(), table
    columns = await session.execute(
        text(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE (table_name = 'stream_subscriptions' AND column_name IN ('cursor_sequence', "
            "'attempts', 'next_attempt_at', 'last_error', 'leased_until', 'lease_owner')) "
            "OR (table_name = 'streams' AND column_name = 'retention_days')"
        )
    )
    assert columns.all() == []


async def test_the_events_view_holds_an_event_once_per_received_time(session):
    ws, stream_id, event_id = str(uuid4()), uuid4(), uuid4()
    await session.execute(
        text(
            "INSERT INTO streams (id, workspace_id, created_by, name, description, kind, "
            "created_at, updated_at) VALUES (:id, :ws, 'u', 'n3', '', 'custom', now(), now())"
        ),
        {"id": stream_id, "ws": ws},
    )
    insert_event = text(
        "INSERT INTO stream_events (received_at, stream_id, event_id, event_key, kind, source, "
        "occurred_at, data, workspace_id, created_by) VALUES (date_trunc('second', now()), :s, "
        ":e, 'k', 'push', 'test', now(), '{}', :ws, 'u')"
    )
    await session.execute(insert_event, {"s": stream_id, "e": event_id, "ws": ws})
    with pytest.raises(IntegrityError, match="duplicate key"):
        await session.execute(insert_event, {"s": stream_id, "e": event_id, "ws": ws})


async def test_a_subscription_reacts_to_an_event_once(session):
    found = await session.execute(
        text(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conname = 'uq_trigger_executions_subscription_event'"
        )
    )
    assert found.scalar_one() == "UNIQUE (subscription_id, event_id)"
    nullable = await session.execute(
        text(
            "SELECT is_nullable FROM information_schema.columns "
            "WHERE table_name = 'trigger_executions' AND column_name = 'trigger_id'"
        )
    )
    assert nullable.scalar_one() == "YES"
