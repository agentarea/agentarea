"""Revisions against the real migrated schema.

The per-agent number is a unique constraint, ``spec`` is jsonb, and an agent row
is locked while its pointer moves; a mocked session checks none of that.

Set SERVING_TEST_DATABASE_URL to a postgresql+asyncpg URL for a disposable,
already-migrated database (``make check-db`` does).
"""

from __future__ import annotations

import os
from uuid import uuid4

import pytest
from agentarea_agents.domain.models import Agent
from agentarea_agents.serving.models import REVISION_ACTIVE, REVISION_ARCHIVED, REVISION_CANDIDATE
from agentarea_agents.serving.revision_service import (
    RevisionNotFoundError,
    RevisionService,
    StaleRevisionError,
    UnchangedRevisionError,
)
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


async def _agent(session, context, **fields) -> Agent:
    agent = Agent(
        name="Researcher",
        slug=f"researcher-{uuid4().hex[:8]}",
        instruction=fields.get("instruction", "Find sources."),
        model_id="m-1",
        tools=[{"type": "mcp", "name": "search"}],
        planning=False,
        a2ui_enabled=False,
        workspace_id=context.workspace_id,
        created_by=context.user_id,
    )
    session.add(agent)
    await session.commit()
    return agent


async def test_ensure_current_creates_the_first_revision_and_points_at_it(session, context):
    agent = await _agent(session, context)

    revision = await RevisionService(session, context).ensure_current(agent, origin="create")

    assert revision.number == 1
    assert revision.status == REVISION_ACTIVE
    assert revision.spec["instruction"] == "Find sources."
    assert agent.current_revision_id == revision.id


async def test_ensure_current_is_idempotent_while_the_config_is_unchanged(session, context):
    agent = await _agent(session, context)
    service = RevisionService(session, context)

    first = await service.ensure_current(agent, origin="create")
    again = await service.ensure_current(agent, origin="detected")

    assert again.id == first.id


async def test_a_changed_config_gets_a_new_revision_and_archives_the_old(session, context):
    agent = await _agent(session, context)
    service = RevisionService(session, context)
    first = await service.ensure_current(agent, origin="create")

    agent.instruction = "Find primary sources."
    await session.commit()
    second = await service.ensure_current(agent, origin="update")

    assert second.number == 2
    assert second.parent_revision_id == first.id
    assert first.status == REVISION_ARCHIVED
    assert agent.current_revision_id == second.id


async def test_candidate_does_not_change_what_serves(session, context):
    agent = await _agent(session, context)
    service = RevisionService(session, context)
    current = await service.ensure_current(agent, origin="create")

    candidate = await service.create_candidate(
        agent,
        {"instruction": "Find sources; cite each."},
        message="cite sources",
        origin="user",
        rationale="answers lacked citations",
        evidence=[{"task_id": str(uuid4())}],
    )

    assert candidate.status == REVISION_CANDIDATE
    assert candidate.parent_revision_id == current.id
    assert agent.current_revision_id == current.id
    assert agent.instruction == "Find sources."


async def test_candidate_identical_to_the_base_is_refused(session, context):
    agent = await _agent(session, context)
    service = RevisionService(session, context)
    await service.ensure_current(agent, origin="create")

    with pytest.raises(UnchangedRevisionError):
        await service.create_candidate(
            agent, {"instruction": "Find sources."}, message=None, origin="user",
            rationale=None, evidence=[],
        )


async def test_activating_a_candidate_writes_its_spec_onto_the_agent(session, context):
    agent = await _agent(session, context)
    service = RevisionService(session, context)
    first = await service.ensure_current(agent, origin="create")
    candidate = await service.create_candidate(
        agent, {"instruction": "Cite."}, message=None, origin="user", rationale=None, evidence=[]
    )

    activated = await service.activate(agent, candidate.id)

    assert activated.status == REVISION_ACTIVE
    assert first.status == REVISION_ARCHIVED
    assert agent.instruction == "Cite."
    assert agent.current_revision_id == candidate.id
    # The agent's columns now hash to the candidate: nothing new to record.
    assert (await service.ensure_current(agent, origin="detected")).id == candidate.id


async def test_rollback_reactivates_an_archived_revision(session, context):
    agent = await _agent(session, context)
    service = RevisionService(session, context)
    first = await service.ensure_current(agent, origin="create")
    agent.instruction = "Changed."
    await session.commit()
    await service.ensure_current(agent, origin="update")

    await service.activate(agent, first.id)

    assert agent.instruction == "Find sources."
    assert agent.current_revision_id == first.id


async def test_a_candidate_whose_base_moved_is_stale(session, context):
    agent = await _agent(session, context)
    service = RevisionService(session, context)
    await service.ensure_current(agent, origin="create")
    candidate = await service.create_candidate(
        agent, {"instruction": "Cite."}, message=None, origin="user", rationale=None, evidence=[]
    )
    agent.instruction = "Someone else edited it."
    await session.commit()
    await service.ensure_current(agent, origin="update")

    assert service.is_stale(candidate, agent)
    with pytest.raises(StaleRevisionError):
        await service.activate(agent, candidate.id)


async def test_another_agents_revision_is_not_found(session, context):
    agent = await _agent(session, context)
    other = await _agent(session, context)
    service = RevisionService(session, context)
    other_revision = await service.ensure_current(other, origin="create")

    with pytest.raises(RevisionNotFoundError):
        await service.activate(agent, other_revision.id)


async def test_revisions_list_newest_first(session, context):
    agent = await _agent(session, context)
    service = RevisionService(session, context)
    await service.ensure_current(agent, origin="create")
    agent.instruction = "v2"
    await session.commit()
    await service.ensure_current(agent, origin="update")

    numbers = [r.number for r in await service.list_revisions(agent.id)]

    assert numbers == [2, 1]
