"""The backfill keeps every webhook URL: same webhook_id, now owned by a source.

Set STREAMS_TEST_DATABASE_URL. Runs the migration's own SQL on rows written
after the database was migrated; the statements are idempotent. Its streams are
inserted by SQL, so they carry no graph tuples until the post-migration
reconcile (``agentarea-api reconcile``) writes them.
"""

import importlib.util
import os
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from agentarea_common.rebac.models import RelationQuery, RelationTuple
from agentarea_common.rebac.ownership_reconcile import reconcile_graph_ownership
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


class _Graph:
    """In-memory tuple store; ``can_read`` follows the resource/project branches of model.fga."""

    def __init__(self, tuples: list[RelationTuple]) -> None:
        self.tuples = {str(t): t for t in tuples}

    async def write_tuple(self, tuple_: RelationTuple) -> None:
        self.tuples[str(tuple_)] = tuple_

    async def delete_tuple(self, tuple_: RelationTuple) -> None:
        self.tuples.pop(str(tuple_), None)

    async def query_all_tuples(self, query: RelationQuery) -> list[RelationTuple]:
        return [
            t
            for t in self.tuples.values()
            if (query.namespace is None or t.namespace == query.namespace)
            and (query.object is None or t.object == query.object)
            and (query.relation is None or t.relation == query.relation)
        ]

    def _has(self, namespace: str, obj: str, relation: str, subject: str) -> bool:
        return f"{namespace}:{obj}#{relation}@{subject}" in self.tuples

    def _subjects(self, namespace: str, obj: str, relation: str) -> list[str]:
        return [
            str(t.subject_id)
            for t in self.tuples.values()
            if (t.namespace, t.object, t.relation) == (namespace, obj, relation)
        ]

    def can_read(self, user: str, resource_id: UUID) -> bool:
        if self._has("resource", str(resource_id), "reader", user):
            return True
        for project in self._subjects("resource", str(resource_id), "project"):
            project_id = project.removeprefix("project:")
            if self._has("project", project_id, "reader", user):
                return True
            for workspace in self._subjects("project", project_id, "workspace"):
                if self._has("Workspace", workspace.removeprefix("Workspace:"), "admin", user):
                    return True
        return False


async def test_a_backfilled_stream_is_readable_once_the_post_migration_reconcile_ran():
    engine = create_async_engine(TEST_DATABASE_URL)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    migration = _migration()
    ws, webhook_id = str(uuid4()), f"wh{uuid4().hex}"
    graph = _Graph(
        [
            RelationTuple(
                namespace="Workspace", object=ws, relation="members", subject_id="User:member"
            )
        ]
    )
    async with maker() as session:
        trigger_id = await _add_trigger(session, ws=ws, webhook_id=webhook_id)
        await _run(session, migration.UPGRADE_SQL)
        stream_id = (await _rows_for(session, trigger_id)).stream_id
        assert not graph.can_read("User:owner", stream_id)
        assert not graph.can_read("User:member", stream_id)

        first = await reconcile_graph_ownership(session, graph)
        second = await reconcile_graph_ownership(session, graph)

        assert graph.can_read("User:owner", stream_id)
        assert graph.can_read("User:member", stream_id)
        assert not graph.can_read("User:stranger", stream_id)
        assert first.written > 0
        assert second.written == 0
        await session.rollback()
    await engine.dispose()
