"""Stream repositories and the journal stay in their workspace with no tenant scope bound.

The tenant hook ships in ``log`` mode, which lets a query through unfiltered when
no scope is bound; these run through a plain session to prove the explicit
workspace filters hold on their own. Set STREAMS_TEST_DATABASE_URL.
"""

import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest
from agentarea_common.auth.context import UserContext
from agentarea_common.base import RepositoryFactory
from agentarea_common.config.streams import EventStreamSettings
from agentarea_common.events.ports import IntegrationEvent
from agentarea_streams.application.stream_service import StreamService
from agentarea_streams.domain import EventFilter, StreamKind, StreamNotFoundError, SubscriptionKind
from agentarea_streams.infrastructure.journal import StreamJournal
from agentarea_streams.infrastructure.repository import (
    StreamRepository,
    StreamSourceRepository,
    StreamSubscriptionRepository,
    SubscriptionOutcomeRepository,
    find_webhook_source,
)
from sqlalchemy import text
from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.getenv("STREAMS_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="STREAMS_TEST_DATABASE_URL not set")

GRANT = "agentarea_common.base.workspace_scoped_repository.grant_resource_owner"


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(TEST_DATABASE_URL)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


def _ctx() -> UserContext:
    return UserContext(user_id="u", workspace_id=str(uuid4()))


def _event(n: int = 1) -> IntegrationEvent:
    return IntegrationEvent(type="github.push", source="webhook:test", data={"n": n})


@dataclass(frozen=True)
class _Owned:
    stream_id: UUID
    source_id: UUID
    webhook_id: str
    credential_key: UUID
    trigger_id: UUID
    subscription_id: UUID
    sequence: int


async def _owned_by(session: AsyncSession, ctx: UserContext) -> _Owned:
    with patch(GRANT, new=AsyncMock()):
        stream = await StreamRepository(session, ctx).add_stream(
            name="shared-name", description="", kind=StreamKind.CUSTOM, retention_days=30
        )
    webhook_id, credential_key = f"wh{uuid4().hex}", uuid4()
    source = await StreamSourceRepository(session, ctx).add_webhook_source(
        stream_id=stream.id,
        webhook_id=webhook_id,
        webhook_type="generic",
        allowed_methods=["POST"],
        validation_rules={},
        webhook_config=None,
        credential_key=credential_key,
    )
    trigger_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO triggers (id, workspace_id, created_by, name, description, agent_id, "
            "trigger_type, is_active, task_parameters, conditions, failure_threshold, "
            "consecutive_failures, validation_rules, created_at, updated_at) VALUES (:id, :ws, "
            "'u', 't', '', :agent, 'webhook', true, '{}', '{}', 5, 0, '{}', now(), now())"
        ),
        {"id": trigger_id, "ws": ctx.workspace_id, "agent": uuid4()},
    )
    subscription = await StreamSubscriptionRepository(session, ctx).add_subscription(
        stream_id=stream.id,
        kind=SubscriptionKind.TRIGGER,
        trigger_id=trigger_id,
        filter=EventFilter(),
        output_stream_ids=[],
        cursor_sequence=0,
    )
    journal = StreamJournal(session, ctx, EventStreamSettings())
    appended = await journal.append(stream.id, _event(), event_key="k")
    await session.execute(
        text(
            "INSERT INTO subscription_outcomes (id, workspace_id, created_by, subscription_id, "
            "stream_id, event_sequence, verdict, derived_sequences, created_at, updated_at) "
            "VALUES (:id, :ws, 'u', :sub, :stream, :seq, 'skipped', '[]', now(), now())"
        ),
        {
            "id": uuid4(),
            "ws": ctx.workspace_id,
            "sub": subscription.id,
            "stream": stream.id,
            "seq": appended.sequence,
        },
    )
    await session.commit()
    return _Owned(
        stream_id=stream.id,
        source_id=source.id,
        webhook_id=webhook_id,
        credential_key=credential_key,
        trigger_id=trigger_id,
        subscription_id=subscription.id,
        sequence=appended.sequence,
    )


async def test_another_workspace_cannot_append_to_or_read_a_stream(session: AsyncSession):
    owner, other = _ctx(), _ctx()
    owned = await _owned_by(session, owner)
    journal = StreamJournal(session, other, EventStreamSettings())

    with pytest.raises(StreamNotFoundError):
        await journal.append(owned.stream_id, _event(2), event_key="intruder")
    await session.rollback()
    with pytest.raises(StreamNotFoundError):
        await journal.last_sequence(owned.stream_id)
    assert await journal.read_after(owned.stream_id, 0, 10) == []
    assert await journal.read_before(owned.stream_id, None, 10) == []
    assert await journal.get(owned.stream_id, owned.sequence) is None

    mine = StreamJournal(session, owner, EventStreamSettings())
    assert [e.data for e in await mine.read_after(owned.stream_id, 0, 10)] == [{"n": 1}]
    assert (await mine.get(owned.stream_id, owned.sequence)) is not None
    assert await mine.last_sequence(owned.stream_id) == owned.sequence


async def test_another_workspace_sees_none_of_the_streams_rows(session: AsyncSession):
    owner, other = _ctx(), _ctx()
    owned = await _owned_by(session, owner)
    with patch(GRANT, new=AsyncMock()):
        own_stream = await StreamRepository(session, other).add_stream(
            name="shared-name", description="", kind=StreamKind.CUSTOM, retention_days=30
        )
    await session.commit()

    named = await StreamRepository(session, other).get_by_name("shared-name")
    assert named is not None and named.id == own_stream.id
    sources = StreamSourceRepository(session, other)
    assert await sources.list_for_stream(owned.stream_id) == []
    assert await sources.find_by_credential_key(owned.credential_key) == []
    subscriptions = StreamSubscriptionRepository(session, other)
    assert await subscriptions.get_for_trigger(owned.trigger_id) is None
    assert await subscriptions.list_for_stream(owned.stream_id) == []
    outcomes = SubscriptionOutcomeRepository(session, other)
    assert await outcomes.list_for_events(owned.stream_id, [owned.sequence]) == []
    assert await outcomes.list_for_subscription(owned.subscription_id, 10) == []

    service = StreamService(RepositoryFactory(session, other), EventStreamSettings())
    assert [s.id for s in await service.list_streams(limit=100, offset=0, ids=None)] == [
        own_stream.id
    ]
    with pytest.raises(StreamNotFoundError):
        await service.delete_stream(owned.stream_id)
    await service.update_trigger_filter(owned.trigger_id, EventFilter(kinds=["changed"]))
    await service.remove_trigger_webhook_sources(owned.credential_key)
    await session.commit()

    assert len(await StreamSourceRepository(session, owner).list_for_stream(owned.stream_id)) == 1
    kept = await StreamSubscriptionRepository(session, owner).get_for_trigger(owned.trigger_id)
    assert kept is not None and kept.filter == EventFilter().model_dump()
    found = await find_webhook_source(session, owned.webhook_id)
    assert found is not None and found.id == owned.source_id


async def test_a_webhook_source_update_must_land_on_one_source_of_this_workspace(
    session: AsyncSession,
):
    owner, other = _ctx(), _ctx()
    owned = await _owned_by(session, owner)

    with pytest.raises(NoResultFound):
        await StreamSourceRepository(session, other).update_webhook_fields(
            owned.source_id, webhook_type="github"
        )
    with pytest.raises(NoResultFound):
        await StreamSourceRepository(session, owner).update_webhook_fields(
            uuid4(), webhook_type="github"
        )
    with pytest.raises(ValueError, match="workspace_id"):
        await StreamSourceRepository(session, owner).update_webhook_fields(
            owned.source_id, workspace_id=other.workspace_id
        )
    await session.rollback()

    await StreamSourceRepository(session, owner).update_webhook_fields(
        owned.source_id, webhook_type="github", validation_rules={"secret": "ref"}
    )
    await session.commit()
    found = await find_webhook_source(session, owned.webhook_id)
    assert found is not None
    await session.refresh(found)
    assert found.webhook_type == "github" and found.workspace_id == owner.workspace_id


async def test_journal_edges(session: AsyncSession):
    ctx = _ctx()
    with patch(GRANT, new=AsyncMock()):
        stream = await StreamRepository(session, ctx).add_stream(
            name="empty", description="", kind=StreamKind.CUSTOM, retention_days=30
        )
    await session.commit()
    journal = StreamJournal(session, ctx, EventStreamSettings())

    assert await journal.last_sequence(stream.id) == 0
    assert await journal.get(stream.id, 1) is None
    with pytest.raises(ValueError, match="event_key"):
        await journal.append(stream.id, _event(), event_key="  ")
    with pytest.raises(StreamNotFoundError):
        await journal.append(uuid4(), _event(), event_key="k")
