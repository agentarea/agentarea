"""A webhook trigger's stream, source and subscription, written together.

Set STREAMS_TEST_DATABASE_URL.
"""

import asyncio
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
from agentarea_streams.domain import (
    EventFilter,
    NotAForwardError,
    SourceFedByTriggerError,
    StreamInUseError,
    StreamNameTakenError,
    StreamNotFoundError,
    StreamSourceNotFoundError,
    SubscriptionNotFoundError,
    TriggerSubscriptionNotFoundError,
)
from agentarea_streams.infrastructure.journal_repository import StreamJournal
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


async def _delete_trigger_row(session, trigger_id: UUID) -> None:
    """What deleting the trigger does to its subscription: the foreign key cascades."""
    await session.execute(text("DELETE FROM triggers WHERE id = :id"), {"id": trigger_id})


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
            found = await service.webhook_source_for_trigger(trigger_id)
            assert found is not None and found.id == source.id
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


async def test_a_second_stream_with_a_taken_name_is_refused_and_the_session_survives():
    engine = create_async_engine(TEST_DATABASE_URL)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    ctx = UserContext(user_id="u", workspace_id=str(uuid4()))
    async with maker() as session:
        with workspace_scope(ctx.workspace_id), patch(GRANT, new=AsyncMock()):
            service = StreamService(RepositoryFactory(session, ctx), EventStreamSettings())
            first = await service.create_stream(name="orders", description="", retention_days=7)
            with pytest.raises(StreamNameTakenError, match="orders"):
                await service.create_stream(name="orders", description="", retention_days=7)
            other = await service.create_stream(name="refunds", description="", retention_days=7)
            await session.commit()
            assert (await service.get_stream(first.id)).name == "orders"
            assert (await service.get_stream(other.id)).name == "refunds"
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


async def test_bindings_report_stream_filter_url_and_last_event():
    engine = create_async_engine(TEST_DATABASE_URL)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    ctx = UserContext(user_id="u", workspace_id=str(uuid4()))
    async with maker() as session:
        with workspace_scope(ctx.workspace_id), patch(GRANT, new=AsyncMock()):
            trigger_id = await _trigger_row(session, ctx.workspace_id)
            service = StreamService(RepositoryFactory(session, ctx), EventStreamSettings())
            stream, _, _ = await service.create_webhook_stream_for_trigger(
                trigger_id=trigger_id,
                trigger_name="t",
                webhook_id=f"wh{uuid4().hex}",
                webhook_type="generic",
                allowed_methods=["POST"],
                validation_rules={},
                webhook_config=None,
                event_types=[],
            )
            await StreamJournal(session, ctx, EventStreamSettings()).append(
                stream.id, IntegrationEvent(type="x", source="s"), event_key="one"
            )
            await session.commit()
            binding = (await service.trigger_bindings([trigger_id]))[trigger_id]
            assert binding.stream_id == stream.id
            assert binding.webhook_id is not None
            assert binding.last_event_at is not None
    await engine.dispose()


async def test_bindings_leave_out_another_workspaces_triggers():
    engine = create_async_engine(TEST_DATABASE_URL)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    owner = UserContext(user_id="u", workspace_id=str(uuid4()))
    other = UserContext(user_id="u", workspace_id=str(uuid4()))
    async with maker() as session:
        with workspace_scope(owner.workspace_id), patch(GRANT, new=AsyncMock()):
            trigger_id = await _trigger_row(session, owner.workspace_id)
            owner_service = StreamService(RepositoryFactory(session, owner), EventStreamSettings())
            await owner_service.create_webhook_stream_for_trigger(
                trigger_id=trigger_id,
                trigger_name="t",
                webhook_id=f"wh{uuid4().hex}",
                webhook_type="generic",
                allowed_methods=["POST"],
                validation_rules={},
                webhook_config=None,
                event_types=[],
            )
            await session.commit()

        other_service = StreamService(RepositoryFactory(session, other), EventStreamSettings())
        with workspace_scope(other.workspace_id):
            assert await other_service.trigger_bindings([trigger_id]) == {}
    await engine.dispose()


async def test_a_standalone_source_holds_its_credentials_under_its_own_id():
    engine = create_async_engine(TEST_DATABASE_URL)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    ctx = UserContext(user_id="u", workspace_id=str(uuid4()))
    async with maker() as session:
        with workspace_scope(ctx.workspace_id), patch(GRANT, new=AsyncMock()):
            service = StreamService(RepositoryFactory(session, ctx), EventStreamSettings())
            stream = await service.create_stream(name="payments", description="", retention_days=7)
            source = await service.add_webhook_source(
                stream_id=stream.id, webhook_type="yookassa", validation_rules={"shop_id": "1"}
            )
            await session.commit()
            assert source.credential_key == source.id
            assert source.webhook_id and len(source.webhook_id) >= 16
            assert source.allowed_methods == ["POST"]
            assert [s.id for s in await service.list_sources(stream.id)] == [source.id]
            assert await service.triggers_feeding(stream.id) == {}
            removed = await service.delete_source(stream.id, source.id)
            await session.commit()
            assert removed.id == source.id
            assert await service.list_sources(stream.id) == []
    await engine.dispose()


async def test_a_stream_is_found_by_its_id_or_its_name_in_its_workspace_only():
    engine = create_async_engine(TEST_DATABASE_URL)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    owner = UserContext(user_id="u", workspace_id=str(uuid4()))
    other = UserContext(user_id="u", workspace_id=str(uuid4()))
    async with maker() as session:
        with workspace_scope(owner.workspace_id), patch(GRANT, new=AsyncMock()):
            service = StreamService(RepositoryFactory(session, owner), EventStreamSettings())
            stream = await service.create_stream(name="sentry", description="", retention_days=7)
            await session.commit()
            assert (await service.find_stream("sentry")).id == stream.id
            assert (await service.find_stream(str(stream.id))).id == stream.id
            with pytest.raises(StreamNotFoundError):
                await service.find_stream("absent")
        with workspace_scope(other.workspace_id):
            elsewhere = StreamService(RepositoryFactory(session, other), EventStreamSettings())
            for name_or_id in ("sentry", str(stream.id)):
                with pytest.raises(StreamNotFoundError):
                    await elsewhere.find_stream(name_or_id)
    await engine.dispose()


async def test_a_source_of_another_stream_is_not_found():
    engine = create_async_engine(TEST_DATABASE_URL)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    ctx = UserContext(user_id="u", workspace_id=str(uuid4()))
    async with maker() as session:
        with workspace_scope(ctx.workspace_id), patch(GRANT, new=AsyncMock()):
            service = StreamService(RepositoryFactory(session, ctx), EventStreamSettings())
            one = await service.create_stream(name="one", description="", retention_days=7)
            two = await service.create_stream(name="two", description="", retention_days=7)
            source = await service.add_webhook_source(
                stream_id=one.id, webhook_type="generic", validation_rules={}
            )
            await session.commit()
            with pytest.raises(StreamSourceNotFoundError):
                await service.delete_source(two.id, source.id)
            with pytest.raises(StreamNotFoundError):
                await service.add_webhook_source(
                    stream_id=uuid4(), webhook_type="generic", validation_rules={}
                )
    await engine.dispose()


async def test_a_live_triggers_source_and_its_stream_cannot_be_deleted():
    engine = create_async_engine(TEST_DATABASE_URL)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    ctx = UserContext(user_id="u", workspace_id=str(uuid4()))
    async with maker() as session:
        with workspace_scope(ctx.workspace_id), patch(GRANT, new=AsyncMock()):
            trigger_id = await _trigger_row(session, ctx.workspace_id)
            service = StreamService(RepositoryFactory(session, ctx), EventStreamSettings())
            stream, source, _ = await service.create_webhook_stream_for_trigger(
                trigger_id=trigger_id,
                trigger_name="deploys",
                webhook_id=f"wh{uuid4().hex}",
                webhook_type="github",
                allowed_methods=["POST"],
                validation_rules={},
                webhook_config=None,
                event_types=[],
            )
            standalone = await service.add_webhook_source(
                stream_id=stream.id, webhook_type="sentry", validation_rules={}
            )
            await session.commit()
            assert await service.triggers_feeding(stream.id) == {source.id: trigger_id}
            with pytest.raises(SourceFedByTriggerError) as refused:
                await service.delete_source(stream.id, source.id)
            assert str(trigger_id) in str(refused.value)
            with pytest.raises(SourceFedByTriggerError):
                await service.delete_stream(stream.id)
            await service.delete_source(stream.id, standalone.id)
            await service.remove_trigger_webhook_sources(trigger_id)
            await session.commit()
            with pytest.raises(StreamInUseError):
                await service.delete_stream(stream.id)
            await _delete_trigger_row(session, trigger_id)
            await service.delete_stream(stream.id)
            await session.commit()
            with pytest.raises(StreamNotFoundError):
                await service.get_stream(stream.id)
    await engine.dispose()


async def test_a_stream_a_trigger_subscribes_to_cannot_be_deleted():
    engine = create_async_engine(TEST_DATABASE_URL)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    ctx = UserContext(user_id="u", workspace_id=str(uuid4()))
    async with maker() as session:
        with workspace_scope(ctx.workspace_id), patch(GRANT, new=AsyncMock()):
            service = StreamService(RepositoryFactory(session, ctx), EventStreamSettings())
            stream = await service.create_stream(name="orders", description="", retention_days=7)
            trigger_id = await _trigger_row(session, ctx.workspace_id)
            await service.subscribe_trigger(
                stream_id=stream.id, trigger_id=trigger_id, event_filter=EventFilter()
            )
            await session.commit()

            with pytest.raises(StreamInUseError) as refused:
                await service.delete_stream(stream.id)
            assert refused.value.trigger_ids == [trigger_id]
            assert str(trigger_id) in str(refused.value)
            assert "delete the trigger" in str(refused.value)
            assert (await service.get_stream(stream.id)).id == stream.id
            assert await service.trigger_subscription(trigger_id) is not None

            await _delete_trigger_row(session, trigger_id)
            await service.delete_stream(stream.id)
            await session.commit()
            with pytest.raises(StreamNotFoundError):
                await service.get_stream(stream.id)
    await engine.dispose()


async def test_a_stream_a_forward_writes_into_cannot_be_deleted_until_the_forward_goes():
    engine = create_async_engine(TEST_DATABASE_URL)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    ctx = UserContext(user_id="u", workspace_id=str(uuid4()))
    async with maker() as session:
        with workspace_scope(ctx.workspace_id), patch(GRANT, new=AsyncMock()):
            service = StreamService(RepositoryFactory(session, ctx), EventStreamSettings())
            source = await service.create_stream(name="in", description="", retention_days=7)
            kept = await service.create_stream(name="kept", description="", retention_days=7)
            target = await service.create_stream(name="target", description="", retention_days=7)
            forward = await service.create_forward(
                stream_id=source.id,
                output_stream_ids=[kept.id, target.id],
                event_filter=EventFilter(),
            )
            await session.commit()

            with pytest.raises(StreamInUseError) as refused:
                await service.delete_stream(target.id)
            assert refused.value.forwards == [(forward.id, source.id)]
            assert str(forward.id) in str(refused.value)
            assert str(source.id) in str(refused.value)

            await service.delete_forward(source.id, forward.id)
            await session.commit()
            assert await service.list_subscriptions(source.id) == []
            await service.delete_stream(target.id)
            await session.commit()
            with pytest.raises(StreamNotFoundError):
                await service.get_stream(target.id)
    await engine.dispose()


async def test_the_input_of_a_forward_can_be_deleted_and_takes_the_forward_with_it():
    engine = create_async_engine(TEST_DATABASE_URL)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    ctx = UserContext(user_id="u", workspace_id=str(uuid4()))
    async with maker() as session:
        with workspace_scope(ctx.workspace_id), patch(GRANT, new=AsyncMock()):
            service = StreamService(RepositoryFactory(session, ctx), EventStreamSettings())
            source = await service.create_stream(name="in", description="", retention_days=7)
            output = await service.create_stream(name="out", description="", retention_days=7)
            await service.create_forward(
                stream_id=source.id, output_stream_ids=[output.id], event_filter=EventFilter()
            )
            await session.commit()
            await service.delete_stream(source.id)
            await service.delete_stream(output.id)
            await session.commit()
    await engine.dispose()


async def test_a_forward_lists_each_output_once():
    engine = create_async_engine(TEST_DATABASE_URL)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    ctx = UserContext(user_id="u", workspace_id=str(uuid4()))
    async with maker() as session:
        with workspace_scope(ctx.workspace_id), patch(GRANT, new=AsyncMock()):
            service = StreamService(RepositoryFactory(session, ctx), EventStreamSettings())
            source = await service.create_stream(name="in", description="", retention_days=7)
            one = await service.create_stream(name="one", description="", retention_days=7)
            two = await service.create_stream(name="two", description="", retention_days=7)
            forward = await service.create_forward(
                stream_id=source.id,
                output_stream_ids=[two.id, one.id, two.id, one.id],
                event_filter=EventFilter(),
            )
            await session.commit()
            assert forward.output_stream_ids == [str(two.id), str(one.id)]
            with pytest.raises(StreamNotFoundError):
                await service.create_forward(
                    stream_id=source.id,
                    output_stream_ids=[one.id, uuid4()],
                    event_filter=EventFilter(),
                )
    await engine.dispose()


async def test_only_a_forward_of_this_stream_is_removed_as_a_forward():
    engine = create_async_engine(TEST_DATABASE_URL)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    owner = UserContext(user_id="u", workspace_id=str(uuid4()))
    other = UserContext(user_id="u", workspace_id=str(uuid4()))
    async with maker() as session:
        with workspace_scope(owner.workspace_id), patch(GRANT, new=AsyncMock()):
            service = StreamService(RepositoryFactory(session, owner), EventStreamSettings())
            source = await service.create_stream(name="in", description="", retention_days=7)
            output = await service.create_stream(name="out", description="", retention_days=7)
            trigger_id = await _trigger_row(session, owner.workspace_id)
            trigger_sub = await service.subscribe_trigger(
                stream_id=source.id, trigger_id=trigger_id, event_filter=EventFilter()
            )
            forward = await service.create_forward(
                stream_id=source.id, output_stream_ids=[output.id], event_filter=EventFilter()
            )
            await session.commit()

            with pytest.raises(NotAForwardError) as refused:
                await service.delete_forward(source.id, trigger_sub.id)
            assert str(trigger_id) in str(refused.value)
            with pytest.raises(SubscriptionNotFoundError):
                await service.delete_forward(output.id, forward.id)
            with pytest.raises(SubscriptionNotFoundError):
                await service.delete_forward(source.id, uuid4())

        with workspace_scope(other.workspace_id):
            elsewhere = StreamService(RepositoryFactory(session, other), EventStreamSettings())
            with pytest.raises(SubscriptionNotFoundError):
                await elsewhere.delete_forward(source.id, forward.id)

        with workspace_scope(owner.workspace_id):
            assert {s.id for s in await service.list_subscriptions(source.id)} == {
                trigger_sub.id,
                forward.id,
            }
    await engine.dispose()


async def test_a_forward_whose_output_was_deleted_before_the_guard_can_be_removed():
    engine = create_async_engine(TEST_DATABASE_URL)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    ctx = UserContext(user_id="u", workspace_id=str(uuid4()))
    async with maker() as session:
        with workspace_scope(ctx.workspace_id), patch(GRANT, new=AsyncMock()):
            service = StreamService(RepositoryFactory(session, ctx), EventStreamSettings())
            source = await service.create_stream(name="in", description="", retention_days=7)
            gone = await service.create_stream(name="gone", description="", retention_days=7)
            live = await service.create_stream(name="live", description="", retention_days=7)
            forward = await service.create_forward(
                stream_id=source.id,
                output_stream_ids=[gone.id, live.id],
                event_filter=EventFilter(),
            )
            # Deleted the way an older release allowed, past the guard.
            await session.execute(text("DELETE FROM streams WHERE id = :id"), {"id": gone.id})
            await session.commit()

            found = await service.get_forward(source.id, forward.id)
            assert await service.existing_outputs(found) == [live.id]
            await service.delete_forward(source.id, forward.id)
            await session.commit()
            assert await service.list_subscriptions(source.id) == []
    await engine.dispose()


async def test_a_delete_waits_for_a_forward_being_created_into_the_stream_and_is_refused():
    engine = create_async_engine(TEST_DATABASE_URL)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    ctx = UserContext(user_id="u", workspace_id=str(uuid4()))
    with workspace_scope(ctx.workspace_id), patch(GRANT, new=AsyncMock()):
        async with maker() as creating, maker() as deleting:
            creator = StreamService(RepositoryFactory(creating, ctx), EventStreamSettings())
            source = await creator.create_stream(name="in", description="", retention_days=7)
            target = await creator.create_stream(name="target", description="", retention_days=7)
            await creating.commit()

            forward = await creator.create_forward(
                stream_id=source.id, output_stream_ids=[target.id], event_filter=EventFilter()
            )
            deleter = StreamService(RepositoryFactory(deleting, ctx), EventStreamSettings())
            delete = asyncio.create_task(deleter.delete_stream(target.id))
            await asyncio.sleep(0.3)
            assert not delete.done()
            await creating.commit()

            with pytest.raises(StreamInUseError) as refused:
                await asyncio.wait_for(delete, timeout=10)
            assert refused.value.forwards == [(forward.id, source.id)]
            await deleting.rollback()
    await engine.dispose()
