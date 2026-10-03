"""Revision, experiment, evaluation and feedback routes against the migrated schema.

The handlers are called directly with a real session; only the graph check and
the Temporal start are replaced.

Set EVALS_TEST_DATABASE_URL (``make check-db`` does).
"""

from __future__ import annotations

import os
from decimal import Decimal
from uuid import uuid4

import pytest
from agentarea_agents.application.agent_service import AgentService
from agentarea_agents.domain.models import Agent
from agentarea_api.api.v1 import agent_experiments, agent_revisions, evals, run_feedback
from agentarea_common.auth.context import UserContext, UserPrincipal
from agentarea_common.base.repository_factory import RepositoryFactory
from agentarea_common.base.tenant_scope import workspace_scope
from agentarea_evals.schemas import (
    CaseCreate,
    EvalRunCreate,
    ExperimentCreate,
    FeedbackCreate,
    RevisionCreate,
    SuiteCreate,
)
from agentarea_tasks.infrastructure.orm import TaskORM
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

TEST_DATABASE_URL = os.getenv("EVALS_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="EVALS_TEST_DATABASE_URL not set")


class _Authz:
    async def can_write_workspace(self, _context, _workspace_id):
        return True


class _Broker:
    async def publish(self, _event):
        return None


@pytest.fixture
def context():
    return UserContext(user_id="person-1", workspace_id=f"ws-{uuid4()}")


@pytest.fixture
async def session(context, monkeypatch):
    async def allow(*_args, **_kwargs):
        return None

    monkeypatch.setattr("agentarea_api.api.v1._serving_common.require_permission", allow)
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


@pytest.fixture
def started(monkeypatch):
    calls = []

    async def fake_start(name, workflow_id, args):
        calls.append((name, workflow_id, args))
        return workflow_id

    for module in (agent_experiments, evals):
        monkeypatch.setattr(module, "start_workflow", fake_start)
    return calls


def _agents(session, context) -> AgentService:
    return AgentService(RepositoryFactory(session, context), _Broker(), authorization_service=_Authz())


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
    await _agents(session, context).revisions().ensure_current(agent, origin="create")
    return agent


async def test_candidate_diff_and_activation_through_the_routes(session, context):
    agent = await _agent(session, context)
    service = _agents(session, context)

    candidate = await agent_revisions.create_candidate(
        str(agent.id), RevisionCreate(instruction="Help briefly.", message="shorter"),
        context, service,
    )
    listed = await agent_revisions.list_revisions(agent.slug, context, service)
    diff = await agent_revisions.diff_revision(str(agent.id), candidate.id, context, None, service)
    activated = await agent_revisions.activate_revision(str(agent.id), candidate.id, context, service)

    assert [r.number for r in listed] == [2, 1]
    assert listed[0].status == "candidate" and not listed[0].stale
    assert [c.field for c in diff] == ["instruction"]
    assert activated.current and agent.instruction == "Help briefly."


async def test_an_unchanged_candidate_is_a_conflict(session, context):
    agent = await _agent(session, context)

    with pytest.raises(HTTPException) as error:
        await agent_revisions.create_candidate(
            str(agent.id), RevisionCreate(instruction="Help."), context, _agents(session, context)
        )

    assert error.value.status_code == 409


async def test_eval_run_and_experiment_start_their_workflows(session, context, started):
    agent = await _agent(session, context)
    service = _agents(session, context)
    candidate = await agent_revisions.create_candidate(
        str(agent.id), RevisionCreate(instruction="Help briefly."), context, service
    )
    suite = await evals.create_suite(SuiteCreate(name="smoke"), context, session)
    await evals.add_case(
        suite.id, CaseCreate(name="hello", input="Say hello",
                             checks=[{"type": "response_contains", "text": "hello"}]),
        context, session,
    )

    run = await evals.start_run(
        str(agent.id),
        EvalRunCreate(suite_id=suite.id, candidate_revision_id=candidate.id,
                      budget_usd=Decimal("2")),
        context, session, service,
    )
    experiment = await agent_experiments.start_experiment(
        str(agent.id),
        ExperimentCreate(candidate_revision_id=candidate.id, auto_promote=True),
        context, session, service,
    )
    detail = await evals.get_run(str(agent.id), run.id, context, session, service)

    assert [name for name, *_ in started] == ["EvalRunWorkflow", "ExperimentMonitorWorkflow"]
    assert started[0][2]["concurrency"] == 3
    assert len(detail.trials_detail) == 2 * 3
    assert experiment.weights == {"control": 90, "candidate": 10}
    assert experiment.offline_passed is False


async def test_feedback_is_for_people_only(session, context):
    agent = await _agent(session, context)
    task = TaskORM(
        agent_id=agent.id, description="x", parameters={}, status="completed",
        task_metadata={}, workspace_id=context.workspace_id, created_by=context.user_id,
    )
    session.add(task)
    await session.commit()
    person = UserPrincipal(user_id=context.user_id)
    integration = UserPrincipal(user_id=context.user_id, api_key_id="key-1")

    with pytest.raises(HTTPException) as refused:
        await run_feedback.rate_run(task.id, FeedbackCreate(rating="bad"), context, integration, session)
    rated = await run_feedback.rate_run(
        task.id, FeedbackCreate(rating="bad", comment="wrong"), context, person, session
    )

    assert refused.value.status_code == 403
    assert rated.rating == "bad"
    assert [f.comment for f in await run_feedback.list_feedback(task.id, context, session)] == ["wrong"]
