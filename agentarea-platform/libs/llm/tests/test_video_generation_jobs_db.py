"""Video jobs stay in their workspace and task, and a finished one is billed once.

Also the kind filter on model instances, which joins the spec in SQL.

Needs a PostgreSQL migrated to head (``LLM_TEST_DATABASE_URL``); skips without one.
``make check-db`` wires it.
"""

import json
import os
import uuid
from decimal import Decimal

import pytest
from agentarea_common.auth.context import UserContext
from agentarea_llm.domain.models import ModelInstance, ModelSpec, ProviderConfig, ProviderSpec
from agentarea_llm.infrastructure.video_generation_job_repository import (
    VideoGenerationJobRepository,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.getenv("LLM_TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="LLM_TEST_DATABASE_URL not set; skipping schema-backed video job tests",
)

# Per process: xdist workers must not delete each other's rows on teardown.
_RUN = uuid.uuid4().hex[:8]
WS_A = f"video-jobs-test-a-{_RUN}"
WS_B = f"video-jobs-test-b-{_RUN}"


@pytest.fixture
async def engine():
    engine = create_async_engine(TEST_DATABASE_URL, echo=False, pool_pre_ping=True)
    yield engine
    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM provider_specs WHERE workspace_id IN (:a, :b)"),
            {"a": WS_A, "b": WS_B},
        )
    await engine.dispose()


@pytest.fixture
def sessions(engine):
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
async def video_instance(sessions) -> uuid.UUID:
    async with sessions() as session:
        provider = ProviderSpec(
            id=uuid.uuid4(),
            provider_key=f"k-{uuid.uuid4().hex[:8]}",
            name="Video provider",
            provider_type="openrouter",
            workspace_id=WS_A,
            created_by="tester",
        )
        config = ProviderConfig(
            id=uuid.uuid4(),
            provider_spec_id=provider.id,
            name="cfg",
            workspace_id=WS_A,
            created_by="tester",
        )
        spec = ModelSpec(
            id=uuid.uuid4(),
            provider_spec_id=provider.id,
            model_name="veo",
            display_name="Veo",
            kind="video",
            workspace_id=WS_A,
            created_by="tester",
        )
        instance = ModelInstance(
            id=uuid.uuid4(),
            provider_config_id=config.id,
            model_spec_id=spec.id,
            name="veo",
            workspace_id=WS_A,
            created_by="tester",
        )
        session.add(provider)
        await session.flush()
        session.add_all([config, spec])
        await session.flush()
        session.add(instance)
        await session.commit()
        return instance.id


def _repo(session: AsyncSession, workspace_id: str) -> VideoGenerationJobRepository:
    return VideoGenerationJobRepository(
        session, UserContext(user_id="tester", workspace_id=workspace_id)
    )


async def test_a_job_is_invisible_from_another_workspace_and_task(sessions, video_instance):
    async with sessions() as session:
        job = await _repo(session, WS_A).create(
            model_instance_id=video_instance,
            task_id="task-1",
            provider_job_id="gen-vid-1-abcdefghijklmnopqrst",
            prompt="waves",
            status="pending",
        )

    async with sessions() as session:
        assert (await _repo(session, WS_A).get_for_task(job.id, "task-1")) is not None
        assert (await _repo(session, WS_A).get_for_task(job.id, "task-2")) is None
        assert (await _repo(session, WS_B).get_for_task(job.id, "task-1")) is None


async def test_a_finished_job_is_billed_to_one_call(sessions, video_instance):
    async with sessions() as session:
        job = await _repo(session, WS_A).create(
            model_instance_id=video_instance,
            task_id="task-1",
            provider_job_id="gen-vid-2-abcdefghijklmnopqrst",
            prompt="waves",
            status="in_progress",
        )

    def record(repo, call_ref):
        return repo.record_saved(
            job.id,
            "media/x.mp4",
            cost_usd=Decimal("1.25"),
            billed_cost=Decimal("125"),
            call_ref=call_ref,
        )

    async with sessions() as session:
        assert await record(_repo(session, WS_B), "t:call-1") is False
        repo = _repo(session, WS_A)
        assert await record(repo, "t:call-1") is True
        assert await record(repo, "t:call-1") is True, "a retry of the billing call"
        assert await record(repo, "t:call-2") is False, "any other call"

    async with sessions() as session:
        saved = await _repo(session, WS_A).get_for_task(job.id, "task-1")
        assert saved is not None
        assert (saved.status, saved.file_path, saved.cost_usd, saved.billed_cost) == (
            "completed",
            "media/x.mp4",
            Decimal("1.25"),
            Decimal("125"),
        )
        assert saved.billed_call_ref == "t:call-1"


async def test_instances_are_listed_by_their_model_kind(sessions, video_instance):
    from agentarea_llm.infrastructure.model_instance_repository import ModelInstanceRepository

    async with sessions() as session:
        repo = ModelInstanceRepository(session, UserContext(user_id="tester", workspace_id=WS_A))

        videos = await repo.list_instances(kind="video")
        chats = await repo.list_instances(kind="chat")

    assert [instance.id for instance in videos] == [video_instance]
    assert video_instance not in [instance.id for instance in chats]


async def test_task_summary_counts_model_cost_with_llm_cost(engine, sessions):
    """The summary's cost is the run's total: LLM calls plus the models tools called."""
    task_id = uuid.uuid4()
    events = [
        ("llm.call.completed", {"cost": "0.5"}),
        ("tool.result", {"success": True, "model_cost": "150"}),
        ("tool.result", {"success": False, "model_cost": "4"}),
        ("tool.result", {"success": True, "service_cost": "9"}),
    ]
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO tasks (id, agent_id, description, status, workspace_id, "
                    "created_by) VALUES (:id, :agent, 'd', 'completed', :w, 't')"
                ),
                {"id": task_id, "agent": uuid.uuid4(), "w": WS_A},
            )
            for event_type, data in events:
                await conn.execute(
                    text(
                        "INSERT INTO task_events (id, task_id, event_type, data, workspace_id, "
                        "created_by) VALUES (:id, :task, :type, CAST(:data AS jsonb), :w, 't')"
                    ),
                    {
                        "id": uuid.uuid4(),
                        "task": task_id,
                        "type": event_type,
                        "data": json.dumps(data),
                        "w": WS_A,
                    },
                )
        async with sessions() as session:
            cost = (
                await session.execute(
                    text("SELECT cost_usd FROM task_summary WHERE task_id = :id"), {"id": task_id}
                )
            ).scalar_one()
        assert cost == Decimal("154.5")
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM task_events WHERE task_id = :id"), {"id": task_id})
            await conn.execute(text("DELETE FROM tasks WHERE id = :id"), {"id": task_id})
