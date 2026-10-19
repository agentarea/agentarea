"""The platform stream against the migrated schema: one per workspace, written by the platform only.

Set STREAMS_TEST_DATABASE_URL.
"""

import os
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest
from agentarea_common.auth.context import UserContext
from agentarea_common.base import RepositoryFactory
from agentarea_common.base.tenant_scope import workspace_scope
from agentarea_common.config.streams import EventStreamSettings
from agentarea_common.constants import PLATFORM_PRINCIPAL_ID
from agentarea_common.events.task_stream import task_event
from agentarea_streams.application.platform_projection import PlatformProjection
from agentarea_streams.application.stream_service import StreamService
from agentarea_streams.domain import (
    EventFilter,
    SourceKind,
    StreamEvent,
    StreamManagedByPlatformError,
    StreamNameTakenError,
)
from agentarea_streams.domain.keys import event_id_for
from agentarea_streams.domain.platform import PLATFORM_SOURCE_TYPE
from agentarea_triggers.infrastructure.causation_repository import (
    StoredCausationChain,
    load_platform_task,
)
from agentarea_triggers.loop_guard import own_task_in_chain
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.getenv("STREAMS_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="STREAMS_TEST_DATABASE_URL not set")

GRANT = "agentarea_common.base.workspace_scoped_repository.grant_resource_owner"


class _Quota:
    async def take(self, _workspace_id, _limit, _now) -> bool:
        return True


class _Bus:
    def __init__(self) -> None:
        self.quota = _Quota()
        self.published: list[StreamEvent] = []

    async def publish(self, event: StreamEvent) -> bool:
        if any(seen.id == event.id for seen in self.published):
            return False
        self.published.append(event)
        return True


@pytest.fixture
async def maker():
    engine = create_async_engine(TEST_DATABASE_URL)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


def _platform_service(session, workspace_id: str) -> StreamService:
    return StreamService(
        RepositoryFactory(
            session, UserContext(user_id=PLATFORM_PRINCIPAL_ID, workspace_id=workspace_id)
        ),
        EventStreamSettings(),
    )


async def _task_row(session, workspace_id: str, **columns) -> UUID:
    task_id = uuid4()
    values = {
        "id": task_id,
        "ws": workspace_id,
        "agent": columns.get("agent_id", uuid4()),
        "origin_type": columns.get("origin_type"),
        "origin_id": columns.get("origin_id"),
        "correlation_id": columns.get("correlation_id", str(task_id)),
        "causation_id": columns.get("causation_id"),
        "depth": columns.get("depth", 0),
    }
    await session.execute(
        text(
            "INSERT INTO tasks (id, agent_id, description, status, workspace_id, created_by, "
            "origin_type, origin_id, correlation_id, causation_id, depth) VALUES (:id, :agent, "
            "'d', 'failed', :ws, 'owner', :origin_type, :origin_id, :correlation_id, "
            ":causation_id, :depth)"
        ),
        values,
    )
    return task_id


async def test_one_platform_stream_and_source_per_workspace(maker):
    workspace_id = str(uuid4())
    async with maker() as session:
        with workspace_scope(workspace_id), patch(GRANT, new=AsyncMock()):
            stream, source = await _platform_service(session, workspace_id).ensure_platform_stream()
            again, same = await _platform_service(session, workspace_id).ensure_platform_stream()
            await session.commit()
    assert (again.id, same.id) == (stream.id, source.id)
    assert (stream.name, stream.kind) == ("platform", "platform")
    assert (source.kind, source.webhook_type, source.webhook_id) == (
        SourceKind.PLATFORM.value,
        PLATFORM_SOURCE_TYPE,
        None,
    )


async def test_a_second_platform_stream_in_a_workspace_is_refused_by_the_schema(maker):
    workspace_id = str(uuid4())
    async with maker() as session:
        await session.execute(
            text(
                "INSERT INTO streams (id, workspace_id, created_by, name, description, kind, "
                "created_at, updated_at) VALUES (:a, :ws, 'p', 'platform', '', 'platform', now(), "
                "now())"
            ),
            {"a": uuid4(), "ws": workspace_id},
        )
        with pytest.raises(Exception, match="uq_streams_platform"):
            await session.execute(
                text(
                    "INSERT INTO streams (id, workspace_id, created_by, name, description, kind, "
                    "created_at, updated_at) VALUES (:b, :ws, 'p', 'other', '', 'platform', "
                    "now(), now())"
                ),
                {"b": uuid4(), "ws": workspace_id},
            )
        await session.rollback()


async def test_members_read_the_platform_stream_but_cannot_change_it(maker):
    workspace_id = str(uuid4())
    member = UserContext(user_id="member", workspace_id=workspace_id)
    async with maker() as session:
        with workspace_scope(workspace_id), patch(GRANT, new=AsyncMock()):
            stream, source = await _platform_service(session, workspace_id).ensure_platform_stream()
            service = StreamService(RepositoryFactory(session, member), EventStreamSettings())
            other = await service.create_stream(name="mine", description="")
            with pytest.raises(StreamNameTakenError, match="platform stream"):
                await service.create_stream(name="platform", description="")
            with pytest.raises(StreamManagedByPlatformError):
                await service.delete_stream(stream.id)
            with pytest.raises(StreamManagedByPlatformError):
                await service.delete_source(stream.id, source.id)
            with pytest.raises(StreamManagedByPlatformError):
                await service.add_source(
                    stream_id=stream.id,
                    kind=SourceKind.WEBHOOK,
                    source_type="generic_webhook",
                    webhook_config={},
                    event_templates=None,
                )
            with pytest.raises(StreamManagedByPlatformError):
                await service.create_forward(
                    stream_id=other.id, output_stream_ids=[stream.id], event_filter=EventFilter()
                )
            assert (await service.get_stream(stream.id)).name == "platform"
            await session.rollback()


async def test_a_failed_task_lands_once_in_the_platform_stream_with_its_chain(maker):
    workspace_id = str(uuid4())
    async with maker() as session:
        task_id = await _task_row(session, workspace_id, correlation_id="chain-1", depth=2)
        await session.commit()
    bus = _Bus()
    projection = PlatformProjection(
        session_factory=maker, settings=EventStreamSettings(), bus=bus, load_task=load_platform_task
    )
    failed = task_event(
        task_id=str(task_id),
        workspace_id=workspace_id,
        event_type="task.failed",
        event_id=str(uuid4()),
        timestamp=datetime.now(UTC),
        data={"error": "model not found", "total_cost": "0", "error_detail": {"x": 1}},
    )
    with patch(GRANT, new=AsyncMock()):
        await projection.handle(failed)
        await projection.handle(failed)
        await projection.handle(
            task_event(
                task_id=str(task_id),
                workspace_id=workspace_id,
                event_type="tool.result",
                event_id=str(uuid4()),
                timestamp=datetime.now(UTC),
                data={"result": "secret output"},
            )
        )
    (event,) = bus.published
    async with maker() as session:
        with workspace_scope(workspace_id):
            stream, source = await _platform_service(session, workspace_id).ensure_platform_stream()
    assert event.id == event_id_for(stream.id, str(failed.id))
    assert (event.stream_id, event.source_id, event.source_type) == (
        stream.id,
        source.id,
        PLATFORM_SOURCE_TYPE,
    )
    assert (event.type, event.subject, event.session_key) == ("task.failed", str(task_id), None)
    assert (event.correlation_id, event.causation_id, event.depth) == ("chain-1", str(failed.id), 3)
    assert event.created_by == "owner"
    body = event.data["body"]
    assert (body["task_id"], body["status"], body["error"]) == (
        str(task_id),
        "failed",
        "model not found",
    )
    assert "error_detail" not in body


async def test_an_event_of_a_task_that_is_gone_is_dropped(maker):
    bus = _Bus()
    projection = PlatformProjection(
        session_factory=maker, settings=EventStreamSettings(), bus=bus, load_task=load_platform_task
    )
    await projection.handle(
        task_event(
            task_id=str(uuid4()),
            workspace_id=str(uuid4()),
            event_type="task.completed",
            event_id=str(uuid4()),
            timestamp=datetime.now(UTC),
            data={},
        )
    )
    assert bus.published == []


async def test_the_stored_chain_finds_the_triggers_own_task_through_the_read_model(maker):
    workspace_id = str(uuid4())
    trigger_id = uuid4()
    async with maker() as session:
        with workspace_scope(workspace_id), patch(GRANT, new=AsyncMock()):
            stream, source = await _platform_service(session, workspace_id).ensure_platform_stream()
        by_trigger = await _task_row(
            session, workspace_id, origin_type="trigger", origin_id=str(trigger_id)
        )
        first_outcome = uuid4()
        await session.execute(
            text(
                "INSERT INTO stream_events (workspace_id, created_by, received_at, stream_id, "
                "event_id, event_key, kind, source, subject, occurred_at, source_id, "
                "source_type, depth, data) VALUES (:ws, 'owner', now(), :stream, :event, 'k', "
                "'task.completed', 'platform', :subject, now(), :source, 'platform', 1, '{}')"
            ),
            {
                "ws": workspace_id,
                "stream": stream.id,
                "event": first_outcome,
                "subject": str(by_trigger),
                "source": source.id,
            },
        )
        by_other = await _task_row(
            session,
            workspace_id,
            origin_type="trigger",
            origin_id=str(uuid4()),
            causation_id=str(first_outcome),
        )
        await session.commit()
        event = StreamEvent(
            type="task.completed",
            source="platform",
            subject=str(by_other),
            stream_id=stream.id,
            workspace_id=workspace_id,
            created_by="owner",
            event_key="k2",
            received_at=datetime.now(UTC),
            depth=2,
            source_type=PLATFORM_SOURCE_TYPE,
        )
        with workspace_scope(workspace_id):
            chain = StoredCausationChain(session, workspace_id)
            assert (
                await own_task_in_chain(chain, trigger_id=trigger_id, event=event, max_hops=8)
                == by_trigger
            )
            assert (
                await own_task_in_chain(chain, trigger_id=uuid4(), event=event, max_hops=8) is None
            )
        other_workspace = StoredCausationChain(session, str(uuid4()))
        assert (
            await own_task_in_chain(other_workspace, trigger_id=trigger_id, event=event, max_hops=8)
            is None
        )


async def test_a_causation_carried_in_from_another_workspace_resolves_nothing_there(maker):
    home, elsewhere = str(uuid4()), str(uuid4())
    trigger_id = uuid4()
    async with maker() as session:
        with workspace_scope(home), patch(GRANT, new=AsyncMock()):
            stream, source = await _platform_service(session, home).ensure_platform_stream()
        by_trigger = await _task_row(session, home, origin_type="trigger", origin_id=str(trigger_id))
        outcome = uuid4()
        await session.execute(
            text(
                "INSERT INTO stream_events (workspace_id, created_by, received_at, stream_id, "
                "event_id, event_key, kind, source, subject, occurred_at, source_id, "
                "source_type, depth, data) VALUES (:ws, 'owner', now(), :stream, :event, 'k', "
                "'task.completed', 'platform', :subject, now(), :source, 'platform', 1, '{}')"
            ),
            {
                "ws": home,
                "stream": stream.id,
                "event": outcome,
                "subject": str(by_trigger),
                "source": source.id,
            },
        )
        carried = await _task_row(
            session,
            elsewhere,
            origin_type="trigger",
            origin_id=str(uuid4()),
            causation_id=str(outcome),
        )
        await session.commit()
        event = StreamEvent(
            type="task.completed",
            source="platform",
            subject=str(carried),
            stream_id=uuid4(),
            workspace_id=elsewhere,
            created_by="owner",
            event_key="k3",
            received_at=datetime.now(UTC),
            depth=2,
            source_type=PLATFORM_SOURCE_TYPE,
        )
        with workspace_scope(elsewhere):
            chain = StoredCausationChain(session, elsewhere)
            assert await chain.event(outcome) is None
            assert (
                await own_task_in_chain(chain, trigger_id=trigger_id, event=event, max_hops=8)
                is None
            )
