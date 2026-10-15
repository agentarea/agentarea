"""A redelivered event whose follow-up was routed into a running workflow queues it once.

The claim is the subscription's reaction row (trigger_executions) for the event,
committed before the signal; a second attempt -- a redelivery after a crash
before the ack, or a second router consumer -- finds it. Set
STREAMS_TEST_DATABASE_URL.
"""

import os
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from agentarea_streams.domain import (
    EventFilter,
    StreamEvent,
    SubscriptionKind,
    SubscriptionView,
)
from agentarea_triggers.stream_subscriber import SubscriptionFollowUpClaim
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.getenv("STREAMS_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="STREAMS_TEST_DATABASE_URL not set")


@pytest.fixture
async def delivery():
    engine = create_async_engine(TEST_DATABASE_URL)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    ws, stream_id, subscription_id, trigger_id = str(uuid4()), uuid4(), uuid4(), uuid4()
    async with maker() as session:
        await session.execute(
            text(
                "INSERT INTO streams (id, workspace_id, created_by, name, description, kind, "
                "created_at, updated_at) VALUES (:id, :ws, 'u', :n, '', 'custom', now(), now())"
            ),
            {"id": stream_id, "ws": ws, "n": f"s-{stream_id}"},
        )
        await session.execute(
            text(
                "INSERT INTO triggers (id, workspace_id, created_by, name, description, agent_id, "
                "trigger_type, is_active, task_parameters, conditions, failure_threshold, "
                "consecutive_failures, validation_rules, created_at, updated_at) VALUES (:id, "
                ":ws, 'u', 't', '', :a, 'stream', true, '{}', '{}', 5, 0, '{}', now(), now())"
            ),
            {"id": trigger_id, "ws": ws, "a": uuid4()},
        )
        await session.execute(
            text(
                "INSERT INTO stream_subscriptions (id, workspace_id, created_by, stream_id, kind, "
                "trigger_id, filter, output_stream_ids, status, created_at, updated_at) VALUES "
                "(:id, :ws, 'u', :s, 'trigger', :t, '{}', '[]', 'active', now(), now())"
            ),
            {"id": subscription_id, "ws": ws, "s": stream_id, "t": trigger_id},
        )
        await session.commit()
    view = SubscriptionView(
        id=subscription_id,
        workspace_id=ws,
        created_by="u",
        stream_id=stream_id,
        kind=SubscriptionKind.TRIGGER,
        trigger_id=trigger_id,
        filter=EventFilter(),
        output_stream_ids=[],
    )
    event = StreamEvent(
        type="message",
        source="webhook:telegram",
        data={"text": "hello again"},
        stream_id=stream_id,
        workspace_id=ws,
        created_by="u",
        event_key="telegram:1",
        received_at=datetime.now(UTC),
    )

    def attempt(session: AsyncSession) -> SubscriptionFollowUpClaim:
        return SubscriptionFollowUpClaim(session, view, event)

    yield maker, attempt, subscription_id
    await engine.dispose()


async def _outcomes(maker, subscription_id) -> list:
    async with maker() as session:
        rows = await session.execute(
            text("SELECT verdict, task_id FROM trigger_executions WHERE subscription_id = :s"),
            {"s": subscription_id},
        )
        return list(rows.fetchall())


async def test_a_second_attempt_finds_the_first_attempts_claim(delivery):
    maker, attempt, subscription_id = delivery
    running = uuid4()
    async with maker() as session:
        first = attempt(session)
        assert await first.delivered_to() is None
        assert await first.claim(running) is True
    async with maker() as session:
        again = attempt(session)
        assert await again.delivered_to() == running
        assert await again.claim(running) is False
    assert [(row.verdict, row.task_id) for row in await _outcomes(maker, subscription_id)] == [
        ("reacted", running)
    ]


async def test_redelivering_a_routed_event_queues_exactly_one_message(delivery):
    from agentarea_tasks.domain.models import AgentTask, Task
    from agentarea_tasks.infrastructure.repository import TaskRepository
    from agentarea_tasks.task_service import TaskService

    maker, attempt, subscription_id = delivery
    now = datetime.now(UTC)
    running = Task(
        id=uuid4(),
        agent_id=uuid4(),
        description="Chat",
        parameters={"channel_origin": {"chat_id": "c-1"}},
        status="running",
        execution_id="task-running",
        user_id="u",
        workspace_id="w",
        created_at=now,
        updated_at=now,
    )
    signals: list[tuple] = []

    async def send_workflow_command(execution_id, command, payload):
        signals.append((execution_id, command, payload))
        return True

    tasks = MagicMock()
    tasks.find_active_by_agent_and_chat = AsyncMock(return_value=[running])
    factory = MagicMock()
    factory.create_repository = MagicMock(
        side_effect=lambda cls: tasks if cls is TaskRepository else MagicMock()
    )
    engine = MagicMock()
    engine.temporal_executor = SimpleNamespace(send_workflow_command=send_workflow_command)
    service = TaskService(
        repository_factory=factory,
        event_broker=AsyncMock(),
        task_manager=engine,
        policy_resolver=AsyncMock(),
    )
    delivery_id = uuid4()

    for _ in range(2):
        async with maker() as session:
            routed = await service.route_or_submit_task(
                AgentTask(
                    id=delivery_id,
                    title="Trigger: chat",
                    description="hello again",
                    query="hello again",
                    user_id="u",
                    workspace_id="w",
                    agent_id=running.agent_id,
                    task_parameters={"channel_origin": {"chat_id": "c-1"}},
                ),
                follow_up_claim=attempt(session),
            )
        assert (routed.status, routed.id) == ("routed", running.id)

    assert signals == [("task-running", "queue_message", {"message": "hello again"})]
    assert [(row.verdict, row.task_id) for row in await _outcomes(maker, subscription_id)] == [
        ("reacted", running.id)
    ]


async def test_a_released_claim_leaves_nothing_behind(delivery):
    maker, attempt, subscription_id = delivery
    async with maker() as session:
        claim = attempt(session)
        assert await claim.claim(uuid4()) is True
        await claim.release()
    assert await _outcomes(maker, subscription_id) == []
    async with maker() as session:
        assert await attempt(session).delivered_to() is None
