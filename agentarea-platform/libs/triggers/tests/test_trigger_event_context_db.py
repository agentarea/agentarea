"""A stream trigger's run is told what event started it, end to end against the schema.

The event goes into the journal, is read back the way the dispatcher reads it,
and the real subscription handler and trigger service fire on it; only the task
service at the end is a stand-in that keeps what it was handed. The trigger is
created through the repository, so its stored row is checked too.
Set STREAMS_TEST_DATABASE_URL.
"""

import json
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from agentarea_common.auth.context import UserContext
from agentarea_common.base import RepositoryFactory
from agentarea_common.base.tenant_scope import tenant_scoped_session_class, workspace_scope
from agentarea_common.config.database import TenantScopeMode
from agentarea_common.config.streams import EventStreamSettings
from agentarea_common.events.ports import IntegrationEvent
from agentarea_execution.activities.agent import config as config_activities
from agentarea_execution.models import AgentConfigRequest
from agentarea_streams.application.dispatcher import _view
from agentarea_streams.application.stream_service import StreamService
from agentarea_streams.domain import EventFilter, HandlerResult, JournaledEvent, Verdict
from agentarea_streams.domain.keys import task_id_for
from agentarea_streams.infrastructure.journal_repository import StreamJournal
from agentarea_streams.infrastructure.orm import StreamSubscriptionORM
from agentarea_triggers.domain.enums import TriggerType
from agentarea_triggers.domain.models import TriggerCreate
from agentarea_triggers.infrastructure.repository import TriggerRepository
from agentarea_triggers.stream_subscriber import TriggerSubscriptionHandler
from agentarea_triggers.trigger_service import TriggerService
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.getenv("STREAMS_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="STREAMS_TEST_DATABASE_URL not set")
GRANT = "agentarea_common.base.workspace_scoped_repository.grant_resource_owner"
INSTRUCTION = "Reply with one short sentence naming the order id in the event"


class _Tasks:
    """The task service boundary: keeps every task it is asked to start."""

    def __init__(self):
        self.submitted: list = []

    async def get_task(self, task_id):
        return None

    async def route_or_submit_task(self, task, *, follow_up_claim=None):
        self.submitted.append(task)
        task.status = "running"
        task.execution_id = f"agent-task-{task.id}"
        return task


@pytest.fixture
async def world():
    engine = create_async_engine(TEST_DATABASE_URL)
    maker = async_sessionmaker(
        engine,
        class_=AsyncSession,
        sync_session_class=tenant_scoped_session_class(TenantScopeMode.ENFORCE),
        expire_on_commit=False,
    )
    raw = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    ctx = UserContext(user_id="u", workspace_id=str(uuid4()))
    settings = EventStreamSettings()
    with workspace_scope(ctx.workspace_id), patch(GRANT, new=AsyncMock()):
        async with maker() as session:
            streams = StreamService(RepositoryFactory(session, ctx), settings)
            stream = await streams.create_stream(
                name="shop orders", description="", retention_days=7
            )
            trigger = await TriggerRepository(session, ctx).create_from_model(
                TriggerCreate(
                    name="Order paid",
                    agent_id=uuid4(),
                    trigger_type=TriggerType.STREAM,
                    task_parameters={"text": INSTRUCTION},
                    created_by="u",
                    workspace_id=ctx.workspace_id,
                    stream_id=stream.id,
                )
            )
            subscription = await streams.subscribe_trigger(
                stream_id=stream.id, trigger_id=trigger.id, event_filter=EventFilter()
            )
            await session.commit()
    yield SimpleNamespace(
        maker=maker,
        raw=raw,
        ctx=ctx,
        settings=settings,
        stream=stream,
        trigger=trigger,
        subscription_id=subscription.id,
    )
    async with raw() as session:
        for table in ("trigger_executions", "triggers", "streams"):
            await session.execute(
                text(f"DELETE FROM {table} WHERE workspace_id = :ws"), {"ws": ctx.workspace_id}
            )
        await session.commit()
    await engine.dispose()


async def _deliver(world, data: dict, *, key: str) -> tuple[_Tasks, JournaledEvent, HandlerResult]:
    """Journal one order.paid event and hand it to the trigger as the dispatcher would."""
    tasks = _Tasks()
    authority = MagicMock()
    authority.may_run = AsyncMock(return_value=True)
    handler = TriggerSubscriptionHandler(
        event_broker=AsyncMock(),
        secret_manager_factory=MagicMock(),
        workflow_executor=MagicMock(),
        authority=authority,
        trigger_service_factory=lambda session, context: TriggerService(
            repository_factory=RepositoryFactory(session, context),
            event_broker=AsyncMock(),
            task_service=tasks,
        ),
    )
    with workspace_scope(world.ctx.workspace_id):
        async with world.maker() as session:
            receipt = await StreamJournal(session, world.ctx, world.settings).append(
                world.stream.id,
                IntegrationEvent(type="order.paid", source="webhook:generic", data=data),
                event_key=key,
            )
            await session.commit()
        async with world.maker() as session:
            event = await StreamJournal(session, world.ctx, world.settings).get(
                world.stream.id, receipt.sequence
            )
            assert event is not None
            view = _view(await session.get(StreamSubscriptionORM, world.subscription_id))
            result = await handler.handle(view, event, session)
            await session.commit()
    return tasks, event, result


async def test_a_stream_trigger_never_stores_a_webhook_type(world):
    async with world.raw() as session:
        stored = await session.scalar(
            text("SELECT webhook_type FROM triggers WHERE id = :id"), {"id": world.trigger.id}
        )
    assert stored is None


async def test_the_runs_first_message_carries_the_order_that_fired_it(world):
    data = {"order": {"id": "A-1003", "total": "42.00", "currency": "EUR"}}
    tasks, event, result = await _deliver(world, data, key="order-A-1003")

    assert result.verdict == Verdict.REACTED
    [task] = tasks.submitted
    assert task.id == task_id_for(world.subscription_id, event.sequence)
    assert task.description == INSTRUCTION
    assert task.query.startswith(f"{INSTRUCTION}\n\n## What started this run")
    assert "A-1003" in task.query
    assert "- Trigger: Order paid (stream)" in task.query
    assert "- Stream: shop orders" in task.query
    assert '- Event kind: "order.paid"' in task.query
    assert '- Event key: "order-A-1003"' in task.query
    assert f"- Stream sequence: {event.sequence}" in task.query
    assert "trigger_event_file" not in task.task_parameters


async def test_a_large_order_reaches_the_run_as_a_task_input_file(world, monkeypatch):
    import agentarea_common.artifacts as artifacts

    data = {
        "order": {"id": "A-2001"},
        "lines": [{"sku": f"SKU-{i}", "note": "n" * 400} for i in range(80)],
    }
    tasks, event, result = await _deliver(world, data, key="order-A-2001")

    assert result.verdict == Verdict.REACTED
    [task] = tasks.submitted
    filename = f"trigger-event-{event.sequence}.json"
    assert task.task_parameters["trigger_event_file"] == filename
    assert f"`inputs/attachments/{filename}`" in task.query
    assert "SKU-79" not in task.query

    stored: dict = {}
    repository = AsyncMock()

    async def read(workspace_id, task_id, path):
        raise FileNotFoundError(path)

    async def put(workspace_id, task_id, files, **kwargs):
        stored.update({(workspace_id, task_id, p): content for p, content in files.items()})

    repository.get.side_effect = read
    repository.put_files.side_effect = put
    monkeypatch.setattr(artifacts, "WorkspaceRepository", MagicMock(return_value=repository))
    descriptors = await config_activities._prepare_trigger_event_file(
        AgentConfigRequest(
            agent_id=task.agent_id,
            task_id=task.id,
            task_parameters=task.task_parameters,
            user_context_data={"user_id": "u", "workspace_id": world.ctx.workspace_id},
        ),
        world.ctx,
    )

    [descriptor] = descriptors
    assert descriptor["relative_path"] == f"inputs/attachments/{filename}"
    content = stored[(world.ctx.workspace_id, str(task.id), descriptor["relative_path"])]
    assert descriptor["size"] == len(content)
    assert json.loads(content) == data
