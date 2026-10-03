"""Run pinning against the real schema: experiments are found by a partial index.

Set SERVING_TEST_DATABASE_URL (``make check-db`` does).
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from agentarea_agents.domain.models import Agent
from agentarea_agents.serving.models import EXPERIMENT_RUNNING, AgentExperiment
from agentarea_agents.serving.pinning import RunPinner
from agentarea_agents.serving.revision_service import RevisionService
from agentarea_common.auth.context import UserContext
from agentarea_common.base.tenant_scope import workspace_scope
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

TEST_DATABASE_URL = os.getenv("SERVING_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="SERVING_TEST_DATABASE_URL not set")


@pytest.fixture
def context():
    return UserContext(user_id="user-a", workspace_id=f"ws-{uuid4()}")


@pytest.fixture
async def session(context):
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.connect() as conn:
        transaction = await conn.begin()
        async with AsyncSession(
            bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
        ) as s:
            with workspace_scope(context.workspace_id):
                yield s
        await transaction.rollback()
    await engine.dispose()


async def _agent(session, context) -> Agent:
    agent = Agent(
        name="Support",
        slug=f"support-{uuid4().hex[:8]}",
        instruction="Help.",
        model_id="m-1",
        tools=[],
        workspace_id=context.workspace_id,
        created_by=context.user_id,
    )
    session.add(agent)
    await session.commit()
    return agent


async def _experiment(session, context, agent, control, candidate, weights) -> AgentExperiment:
    experiment = AgentExperiment(
        agent_id=agent.id,
        control_revision_id=control.id,
        candidate_revision_id=candidate.id,
        status=EXPERIMENT_RUNNING,
        weights=weights,
        policy={},
        started_at=datetime.now(UTC),
        workspace_id=context.workspace_id,
        created_by=context.user_id,
    )
    session.add(experiment)
    await session.commit()
    return experiment


async def test_without_an_experiment_a_run_gets_the_current_revision(session, context):
    agent = await _agent(session, context)

    pin = await RunPinner(session, context).pin(agent, uuid4())

    assert pin.revision_id == agent.current_revision_id
    assert pin.experiment_id is None
    assert pin.arm is None


async def test_a_running_experiment_assigns_by_weight(session, context):
    agent = await _agent(session, context)
    revisions = RevisionService(session, context)
    control = await revisions.ensure_current(agent, origin="create")
    candidate = await revisions.create_candidate(
        agent, {"instruction": "Help, briefly."}, message=None, origin="user",
        rationale=None, evidence=[],
    )
    experiment = await _experiment(
        session, context, agent, control, candidate, {"control": 0, "candidate": 100}
    )

    pin = await RunPinner(session, context).pin(agent, uuid4())

    assert pin.revision_id == candidate.id
    assert pin.experiment_id == experiment.id
    assert pin.arm == "candidate"


async def test_an_experiment_whose_control_stopped_serving_ends_as_stale(session, context):
    agent = await _agent(session, context)
    revisions = RevisionService(session, context)
    control = await revisions.ensure_current(agent, origin="create")
    candidate = await revisions.create_candidate(
        agent, {"instruction": "Help, briefly."}, message=None, origin="user",
        rationale=None, evidence=[],
    )
    experiment = await _experiment(
        session, context, agent, control, candidate, {"control": 0, "candidate": 100}
    )
    agent.instruction = "Edited by hand."
    await session.commit()

    pin = await RunPinner(session, context).pin(agent, uuid4())

    assert pin.revision_id == agent.current_revision_id
    assert pin.experiment_id is None
    assert experiment.status == "stopped"
    assert experiment.stop_reason == "stale"
