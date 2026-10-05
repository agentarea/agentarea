"""A webhook trigger's stream, source and subscription, written together.

Set STREAMS_TEST_DATABASE_URL.
"""

import os
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest
from agentarea_common.auth.context import UserContext
from agentarea_common.base import RepositoryFactory
from agentarea_common.base.tenant_scope import workspace_scope
from agentarea_common.config.streams import EventStreamSettings
from agentarea_common.events.ports import IntegrationEvent
from agentarea_streams.application.stream_service import StreamService
from agentarea_streams.domain import EventFilter, TriggerSubscriptionNotFoundError
from agentarea_streams.infrastructure.journal import StreamJournal
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.getenv("STREAMS_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="STREAMS_TEST_DATABASE_URL not set")

GRANT = "agentarea_common.base.workspace_scoped_repository.grant_resource_owner"


async def _trigger_row(session, ws: str) -> UUID:
    trigger_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO triggers (id, workspace_id, created_by, name, description, agent_id, "
            "trigger_type, is_active, task_parameters, conditions, failure_threshold, "
            "consecutive_failures, validation_rules, created_at, updated_at) VALUES (:id, :ws, "
            "'u', 't', '', :agent, 'webhook', true, '{}', '{}', 5, 0, '{}', now(), now())"
        ),
        {"id": trigger_id, "ws": ws, "agent": uuid4()},
    )
    return trigger_id


async def test_a_webhook_trigger_gets_a_stream_a_source_and_a_subscription():
    engine = create_async_engine(TEST_DATABASE_URL)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    ctx = UserContext(user_id="u", workspace_id=str(uuid4()))
    async with maker() as session:
        with workspace_scope(ctx.workspace_id), patch(GRANT, new=AsyncMock()):
            trigger_id = await _trigger_row(session, ctx.workspace_id)
            service = StreamService(RepositoryFactory(session, ctx), EventStreamSettings())
            webhook_id = f"wh{uuid4().hex}"
            stream, source, sub = await service.create_webhook_stream_for_trigger(
                trigger_id=trigger_id,
                trigger_name="GitHub pushes",
                webhook_id=webhook_id,
                webhook_type="github",
                allowed_methods=["POST"],
                validation_rules={},
                webhook_config=None,
                event_types=["push"],
            )
            await session.commit()
            assert source.webhook_id == webhook_id
            assert source.credential_key == trigger_id
            assert sub.trigger_id == trigger_id
            assert EventFilter.model_validate(sub.filter).kinds == ["push"]
            assert (await service.webhook_source_for_trigger(trigger_id)).id == source.id
            await service.remove_trigger_webhook_sources(trigger_id)
            await session.commit()
            assert await service.webhook_source_for_trigger(trigger_id) is None
            assert (await service.get_stream(stream.id)).id == stream.id
    await engine.dispose()


async def test_a_new_subscription_starts_after_the_events_already_there():
    engine = create_async_engine(TEST_DATABASE_URL)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    ctx = UserContext(user_id="u", workspace_id=str(uuid4()))
    async with maker() as session:
        with workspace_scope(ctx.workspace_id), patch(GRANT, new=AsyncMock()):
            service = StreamService(RepositoryFactory(session, ctx), EventStreamSettings())
            stream = await service.create_stream(name="feed", description="", retention_days=7)
            journal = StreamJournal(session, ctx, EventStreamSettings())
            appended = await journal.append(
                stream.id, IntegrationEvent(type="x", source="s"), event_key="old"
            )
            trigger_id = await _trigger_row(session, ctx.workspace_id)
            sub = await service.subscribe_trigger(
                stream_id=stream.id, trigger_id=trigger_id, event_filter=EventFilter()
            )
            await session.commit()
            assert sub.cursor_sequence == appended.sequence
    await engine.dispose()


async def test_updating_an_unknown_triggers_filter_raises():
    engine = create_async_engine(TEST_DATABASE_URL)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    ctx = UserContext(user_id="u", workspace_id=str(uuid4()))
    async with maker() as session:
        with workspace_scope(ctx.workspace_id), patch(GRANT, new=AsyncMock()):
            service = StreamService(RepositoryFactory(session, ctx), EventStreamSettings())
            with pytest.raises(TriggerSubscriptionNotFoundError):
                await service.update_trigger_filter(uuid4(), EventFilter(kinds=["x"]))
    await engine.dispose()


async def test_updating_another_workspaces_trigger_filter_raises():
    engine = create_async_engine(TEST_DATABASE_URL)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    owner = UserContext(user_id="u", workspace_id=str(uuid4()))
    other = UserContext(user_id="u", workspace_id=str(uuid4()))
    async with maker() as session:
        with workspace_scope(owner.workspace_id), patch(GRANT, new=AsyncMock()):
            trigger_id = await _trigger_row(session, owner.workspace_id)
            owner_service = StreamService(RepositoryFactory(session, owner), EventStreamSettings())
            stream = await owner_service.create_stream(
                name="feed3", description="", retention_days=7
            )
            await owner_service.subscribe_trigger(
                stream_id=stream.id, trigger_id=trigger_id, event_filter=EventFilter()
            )
            await session.commit()

        other_service = StreamService(RepositoryFactory(session, other), EventStreamSettings())
        with workspace_scope(other.workspace_id):
            with pytest.raises(TriggerSubscriptionNotFoundError):
                await other_service.update_trigger_filter(trigger_id, EventFilter(kinds=["x"]))

        kept = await owner_service.trigger_subscription(trigger_id)
        assert kept is not None and kept.filter == EventFilter().model_dump()
    await engine.dispose()
