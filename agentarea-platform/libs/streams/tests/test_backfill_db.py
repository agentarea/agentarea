"""The backfill keeps every webhook URL: same webhook_id, now owned by a source.

Set STREAMS_TEST_DATABASE_URL. Runs the migration's own SQL on rows written
after the database was migrated; the statements are idempotent.
"""

import importlib.util
import os
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.getenv("STREAMS_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="STREAMS_TEST_DATABASE_URL not set")

MIGRATION = (
    Path(__file__).resolve().parents[3]
    / "apps/api/alembic/versions/20261006_0920_webhook_sources_backfill.py"
)


def _migration():
    spec = importlib.util.spec_from_file_location("backfill", MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _add_trigger(
    session: AsyncSession,
    *,
    ws: str,
    webhook_id: str,
    name: str = "GitHub",
    allowed_methods: str = '["POST"]',
    webhook_type: str | None = "github",
    validation_rules: str = "{}",
    event_types: str = '["push"]',
) -> UUID:
    trigger_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO triggers (id, workspace_id, created_by, name, description, agent_id, "
            "trigger_type, is_active, task_parameters, conditions, failure_threshold, "
            "consecutive_failures, webhook_id, allowed_methods, webhook_type, validation_rules, "
            "event_types, created_at, updated_at) VALUES (:id, :ws, 'owner', :name, '', "
            ":agent, 'webhook', true, '{}', '{}', 5, 0, :wh, CAST(:methods AS json), :type, "
            "CAST(:rules AS json), CAST(:events AS json), now(), now())"
        ),
        {
            "id": trigger_id,
            "ws": ws,
            "name": name,
            "agent": uuid4(),
            "wh": webhook_id,
            "methods": allowed_methods,
            "type": webhook_type,
            "rules": validation_rules,
            "events": event_types,
        },
    )
    return trigger_id


async def _run(session: AsyncSession, statements: list[str]) -> None:
    for statement in statements:
        await session.execute(text(statement))


async def _rows_for(session: AsyncSession, trigger_id: UUID) -> Any:
    return (
        await session.execute(
            text(
                "SELECT st.id AS stream_id, st.name, so.id AS source_id, so.webhook_id, "
                "sub.id AS subscription_id, sub.filter FROM stream_subscriptions sub "
                "JOIN streams st ON st.id = sub.stream_id "
                "JOIN stream_sources so ON so.stream_id = st.id WHERE sub.trigger_id = :t"
            ),
            {"t": trigger_id},
        )
    ).one()


async def test_round_trip_keeps_the_webhook_url_and_the_event_filter():
    engine = create_async_engine(TEST_DATABASE_URL)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    migration = _migration()
    ws, webhook_id = str(uuid4()), f"wh{uuid4().hex}"
    async with maker() as session:
        trigger_id = await _add_trigger(session, ws=ws, webhook_id=webhook_id)
        await _run(session, migration.UPGRADE_SQL)
        await _run(session, migration.UPGRADE_SQL)

        source = (
            await session.execute(
                text(
                    "SELECT webhook_id, webhook_type, credential_key, workspace_id, created_by "
                    "FROM stream_sources WHERE webhook_id = :wh"
                ),
                {"wh": webhook_id},
            )
        ).one()
        assert source.credential_key == trigger_id
        assert (source.workspace_id, source.created_by) == (ws, "owner")
        sub = (
            await session.execute(
                text("SELECT filter, cursor_sequence FROM stream_subscriptions WHERE trigger_id = :t"),
                {"t": trigger_id},
            )
        ).one()
        assert sub.filter["kinds"] == ["push"]
        assert sub.cursor_sequence == 0
        first = await _rows_for(session, trigger_id)
        assert first.name == f"GitHub ({webhook_id})"

        await _run(session, migration.DOWNGRADE_SQL)
        gone = await session.execute(
            text("SELECT count(*) FROM stream_sources WHERE webhook_id = :wh"), {"wh": webhook_id}
        )
        assert gone.scalar_one() == 0

        await _run(session, migration.UPGRADE_SQL)
        assert await _rows_for(session, trigger_id) == first
        await session.rollback()
    await engine.dispose()


async def test_sources_behave_like_triggers_stored_with_json_nulls_and_empty_methods():
    engine = create_async_engine(TEST_DATABASE_URL)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    migration = _migration()
    ws = str(uuid4())
    async with maker() as session:
        nulls = await _add_trigger(
            session,
            ws=ws,
            webhook_id=f"wh{uuid4().hex}",
            allowed_methods="null",
            webhook_type=None,
            validation_rules="null",
            event_types="null",
        )
        empty = await _add_trigger(
            session, ws=ws, webhook_id=f"wh{uuid4().hex}", allowed_methods="[]", webhook_type=""
        )
        await _run(session, migration.UPGRADE_SQL)

        for trigger_id in (nulls, empty):
            source = (
                await session.execute(
                    text(
                        "SELECT allowed_methods, webhook_type, validation_rules FROM stream_sources "
                        "WHERE credential_key = :t"
                    ),
                    {"t": trigger_id},
                )
            ).one()
            assert source.allowed_methods == ["POST"]
            assert source.webhook_type == "generic"
            assert source.validation_rules == {}
        sub_filter = (
            await session.execute(
                text("SELECT filter FROM stream_subscriptions WHERE trigger_id = :t"), {"t": nulls}
            )
        ).scalar_one()
        assert sub_filter == {"kinds": [], "fields": {}}
        await session.rollback()
    await engine.dispose()


async def test_a_webhook_the_app_already_moved_is_left_alone_both_ways():
    engine = create_async_engine(TEST_DATABASE_URL)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    migration = _migration()
    ws, webhook_id = str(uuid4()), f"wh{uuid4().hex}"
    async with maker() as session:
        trigger_id = await _add_trigger(session, ws=ws, webhook_id=webhook_id)
        stream_id = uuid4()
        await session.execute(
            text(
                "INSERT INTO streams (id, workspace_id, created_by, name, description, kind, "
                "retention_days) VALUES (:id, :ws, 'owner', :name, 'Webhook github', 'custom', 30)"
            ),
            {"id": stream_id, "ws": ws, "name": f"GitHub ({webhook_id})"},
        )
        await session.execute(
            text(
                "INSERT INTO stream_sources (id, workspace_id, created_by, stream_id, kind, "
                "webhook_id, webhook_type, allowed_methods, credential_key) VALUES (:id, :ws, "
                "'owner', :stream, 'webhook', :wh, 'github', '[\"POST\"]', :t)"
            ),
            {"id": uuid4(), "ws": ws, "stream": stream_id, "wh": webhook_id, "t": trigger_id},
        )
        await session.execute(
            text(
                "INSERT INTO stream_subscriptions (id, workspace_id, created_by, stream_id, kind, "
                "trigger_id) VALUES (:id, :ws, 'owner', :stream, 'trigger', :t)"
            ),
            {"id": uuid4(), "ws": ws, "stream": stream_id, "t": trigger_id},
        )

        await _run(session, migration.UPGRADE_SQL)

        assert (await _rows_for(session, trigger_id)).stream_id == stream_id
        streams = await session.execute(
            text("SELECT count(*) FROM streams WHERE workspace_id = :ws"), {"ws": ws}
        )
        assert streams.scalar_one() == 1

        await _run(session, migration.DOWNGRADE_SQL)
        assert (await _rows_for(session, trigger_id)).stream_id == stream_id
        await session.rollback()
    await engine.dispose()


async def test_two_triggers_sharing_a_webhook_id_stop_the_backfill_by_name():
    engine = create_async_engine(TEST_DATABASE_URL)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    migration = _migration()
    ws, webhook_id = str(uuid4()), f"wh{uuid4().hex}"
    async with maker() as session:
        await _add_trigger(session, ws=ws, webhook_id=webhook_id)
        await _add_trigger(session, ws=ws, webhook_id=webhook_id)
        with pytest.raises(DBAPIError, match=f"cannot each own a source: {webhook_id}"):
            await _run(session, migration.UPGRADE_SQL)
        await session.rollback()
    await engine.dispose()


async def test_a_long_name_and_webhook_id_still_fit_the_stream_name():
    engine = create_async_engine(TEST_DATABASE_URL)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    migration = _migration()
    ws, webhook_id = str(uuid4()), "w" * 168 + uuid4().hex
    async with maker() as session:
        trigger_id = await _add_trigger(session, ws=ws, webhook_id=webhook_id, name="n" * 200)
        await _run(session, migration.UPGRADE_SQL)

        rows = await _rows_for(session, trigger_id)
        assert rows.webhook_id == webhook_id
        assert len(rows.name) <= 255
        assert rows.name.endswith(f" ({webhook_id})")
        await session.rollback()
    await engine.dispose()
