"""Feedback and outcome stats against the real schema (task_summary is a view).

Set EVALS_TEST_DATABASE_URL (``make check-db`` does).
"""

from uuid import uuid4

import pytest
from agentarea_agents.serving.revision_service import RevisionService
from agentarea_common.auth.context import UserContext
from agentarea_evals.feedback.service import FeedbackService, UnknownRunError
from agentarea_evals.outcomes.stats import OutcomeStats

from .conftest import make_agent, make_task, needs_db

pytestmark = needs_db


async def test_rating_again_replaces_the_previous_verdict(session, context):
    agent = await make_agent(session, context)
    task = await make_task(session, context, agent, status="completed")
    service = FeedbackService(session, context)

    await service.rate(task.id, "good", comment=None, event_id=None)
    await service.rate(task.id, "bad", comment="wrong answer", event_id=None)

    feedback = await service.list_for_task(task.id)
    assert [(f.rating, f.comment) for f in feedback] == [("bad", "wrong answer")]


async def test_two_people_each_keep_their_own_verdict(session, context):
    agent = await make_agent(session, context)
    task = await make_task(session, context, agent, status="completed")
    other = UserContext(user_id="user-b", workspace_id=context.workspace_id)

    await FeedbackService(session, context).rate(task.id, "good", comment=None, event_id=None)
    await FeedbackService(session, other).rate(task.id, "bad", comment=None, event_id=None)

    ratings = sorted(f.rating for f in await FeedbackService(session, context).list_for_task(task.id))
    assert ratings == ["bad", "good"]


async def test_rating_a_run_of_another_workspace_is_refused(session, context):
    agent = await make_agent(session, context)
    task = await make_task(session, context, agent, status="completed")
    stranger = UserContext(user_id="user-c", workspace_id=f"ws-{uuid4()}")

    with pytest.raises(UnknownRunError):
        from agentarea_common.base.tenant_scope import workspace_scope

        with workspace_scope(stranger.workspace_id):
            await FeedbackService(session, stranger).rate(
                task.id, "bad", comment=None, event_id=None
            )


async def test_an_unknown_rating_is_refused(session, context):
    agent = await make_agent(session, context)
    task = await make_task(session, context, agent, status="completed")

    with pytest.raises(ValueError, match="rating"):
        await FeedbackService(session, context).rate(task.id, "meh", comment=None, event_id=None)


async def test_stats_by_revision_count_outcomes_and_feedback(session, context):
    agent = await make_agent(session, context)
    revisions = RevisionService(session, context)
    first = await revisions.ensure_current(agent, origin="create")
    agent.instruction = "Help more."
    await session.commit()
    second = await revisions.ensure_current(agent, origin="update")

    for status in ("completed", "completed", "failed", "running"):
        await make_task(session, context, agent, status=status, revision_id=first.id)
    rated = await make_task(session, context, agent, status="completed", revision_id=second.id)
    await make_task(session, context, agent, status="cancelled", revision_id=second.id)
    await make_task(
        session, context, agent, status="failed", revision_id=second.id,
        metadata={"run_mode": "evaluation"},
    )
    await FeedbackService(session, context).rate(rated.id, "bad", comment=None, event_id=None)

    summaries = {s.revision_id: s for s in await OutcomeStats(session, context).by_revision(agent.id)}

    assert (summaries[first.id].successes, summaries[first.id].failures) == (2, 1)
    assert summaries[first.id].pending == 1
    assert (summaries[second.id].successes, summaries[second.id].failures) == (0, 1)
    assert summaries[second.id].excluded == 1


async def test_stats_for_an_experiment_split_by_revision(session, context):
    agent = await make_agent(session, context)
    revisions = RevisionService(session, context)
    control = await revisions.ensure_current(agent, origin="create")
    candidate = await revisions.create_candidate(
        agent, {"instruction": "Briefly."}, message=None, origin="user", rationale=None,
        evidence=[],
    )
    experiment_id = uuid4()
    await make_task(session, context, agent, status="completed", revision_id=control.id)

    arms = await OutcomeStats(session, context).by_revision(
        agent.id, revision_ids=[control.id, candidate.id], experiment_id=experiment_id
    )

    assert arms == []
