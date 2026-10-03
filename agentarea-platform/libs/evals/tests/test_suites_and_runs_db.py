"""Suites, cases and run bookkeeping against the real schema.

Set EVALS_TEST_DATABASE_URL (``make check-db`` does).
"""

from decimal import Decimal
from uuid import uuid4

import pytest
from agentarea_agents.serving.revision_service import RevisionService
from agentarea_evals.runs.service import EvalRunError, EvalRunService
from agentarea_evals.suites.checks import TrialOutcome
from agentarea_evals.suites.service import SuiteError, SuiteService
from agentarea_tasks.infrastructure.orm import TaskConversationEntryORM

from .conftest import make_agent, make_task, needs_db

pytestmark = needs_db


async def _suite_with_cases(session, context, count=2):
    suites = SuiteService(session, context)
    suite = await suites.create_suite("Support regressions", "real tickets")
    for i in range(count):
        await suites.add_case(
            suite.id, name=f"case {i}", input=f"question {i}", parameters={},
            checks=[{"type": "response_contains", "text": "answer"}], stubs={},
        )
    return suites, suite


async def test_a_case_with_a_bad_check_is_refused(session, context):
    suites = SuiteService(session, context)
    suite = await suites.create_suite("s", None)

    with pytest.raises(ValueError, match="unknown check"):
        await suites.add_case(suite.id, name="c", input="x", parameters={},
                              checks=[{"type": "vibes"}], stubs={})


async def test_a_case_cannot_carry_run_overrides(session, context):
    suites = SuiteService(session, context)
    suite = await suites.create_suite("s", None)

    with pytest.raises(SuiteError, match="model_override"):
        await suites.add_case(suite.id, name="c", input="x",
                              parameters={"model_override": "m-9"}, checks=[], stubs={})


async def test_a_case_harvested_from_a_run_carries_its_input_and_tool_answers(session, context):
    agent = await make_agent(session, context)
    task = await make_task(session, context, agent, status="completed")
    task.parameters = {"files": ["inputs/sales.csv"], "model_override": "m-2"}
    task.description = "Summarize sales.csv"
    session.add_all([
        TaskConversationEntryORM(
            task_id=task.id, seq=1, kind="message", role="assistant", content="",
            tool_calls=[{"id": "call-1", "function": {"name": "mcp__crm__lookup"}}],
            workspace_id=context.workspace_id, created_by=context.user_id,
        ),
        TaskConversationEntryORM(
            task_id=task.id, seq=2, kind="message", role="tool", content='{"rows": 3}',
            tool_call_id="call-1", workspace_id=context.workspace_id,
            created_by=context.user_id,
        ),
    ])
    await session.commit()
    suites = SuiteService(session, context)
    suite = await suites.create_suite("s", None)

    case = await suites.case_from_task(suite.id, task.id)

    assert case.input == "Summarize sales.csv"
    assert case.parameters == {"files": ["inputs/sales.csv"]}
    assert case.stubs == {"mcp__crm__lookup": '{"rows": 3}'}
    assert case.source_task_id == task.id


async def test_create_run_lays_out_every_trial(session, context):
    agent = await make_agent(session, context)
    revisions = RevisionService(session, context)
    baseline = await revisions.ensure_current(agent, origin="create")
    candidate = await revisions.create_candidate(
        agent, {"instruction": "Answer."}, message=None, origin="user", rationale=None,
        evidence=[],
    )
    _, suite = await _suite_with_cases(session, context, count=2)

    run = await EvalRunService(session, context).create_run(
        suite.id, agent, baseline_revision_id=None, candidate_revision_id=candidate.id,
        trials=3, concurrency=2, budget_usd=Decimal("5"), allow_sandbox=False,
    )

    trials = await EvalRunService(session, context).trials(run.id)
    assert run.baseline_revision_id == baseline.id
    assert len(trials) == 2 * 2 * 3
    assert {t.status for t in trials} == {"pending"}


async def test_a_run_needs_a_budget_and_cases(session, context):
    agent = await make_agent(session, context)
    suites = SuiteService(session, context)
    empty = await suites.create_suite("empty", None)
    service = EvalRunService(session, context)

    with pytest.raises(EvalRunError, match="no cases"):
        await service.create_run(empty.id, agent, baseline_revision_id=None,
                                 candidate_revision_id=None, trials=1, concurrency=1,
                                 budget_usd=Decimal("1"), allow_sandbox=False)
    _, suite = await _suite_with_cases(session, context, count=1)
    with pytest.raises(EvalRunError, match="budget"):
        await service.create_run(suite.id, agent, baseline_revision_id=None,
                                 candidate_revision_id=None, trials=1, concurrency=1,
                                 budget_usd=Decimal("0"), allow_sandbox=False)


async def test_a_sandbox_agent_needs_the_sandbox_allowed(session, context):
    agent = await make_agent(session, context)
    agent.tools = [{"type": "code", "name": "agentarea/shell"}]
    await session.commit()
    _, suite = await _suite_with_cases(session, context, count=1)
    service = EvalRunService(session, context)

    with pytest.raises(EvalRunError, match="sandbox"):
        await service.create_run(suite.id, agent, baseline_revision_id=None,
                                 candidate_revision_id=None, trials=1, concurrency=1,
                                 budget_usd=Decimal("1"), allow_sandbox=False)
    run = await service.create_run(suite.id, agent, baseline_revision_id=None,
                                   candidate_revision_id=None, trials=1, concurrency=1,
                                   budget_usd=Decimal("1"), allow_sandbox=True)
    assert run.summary["sandbox_allowed"] is True


async def test_claim_grade_and_finalize(session, context):
    agent = await make_agent(session, context)
    _, suite = await _suite_with_cases(session, context, count=1)
    service = EvalRunService(session, context)
    run = await service.create_run(suite.id, agent, baseline_revision_id=None,
                                   candidate_revision_id=None, trials=2, concurrency=1,
                                   budget_usd=Decimal("1"), allow_sandbox=False)

    claimed = await service.claim(run.id, limit=5)
    assert len(claimed) == 2
    for trial in claimed:
        await service.record_outcome(
            trial.id,
            TrialOutcome(status="completed", response="the answer", cost_usd=0.1),
        )
    finished = await service.finalize(run.id)

    assert finished.status == "completed"
    assert finished.summary["passed"] is True
    assert finished.cost_usd == Decimal("0.2000")


async def test_running_over_budget_stops_the_run(session, context):
    agent = await make_agent(session, context)
    _, suite = await _suite_with_cases(session, context, count=1)
    service = EvalRunService(session, context)
    run = await service.create_run(suite.id, agent, baseline_revision_id=None,
                                   candidate_revision_id=None, trials=3, concurrency=1,
                                   budget_usd=Decimal("0.15"), allow_sandbox=False)

    first, *_ = await service.claim(run.id, limit=1)
    await service.record_outcome(first.id, TrialOutcome(status="completed", response="answer", cost_usd=0.2))

    assert run.status == "stopped"
    assert run.stop_reason == "budget"
    assert await service.claim(run.id, limit=5) == []


async def test_offline_pass_is_the_latest_finished_run_for_a_candidate(session, context):
    agent = await make_agent(session, context)
    revisions = RevisionService(session, context)
    await revisions.ensure_current(agent, origin="create")
    candidate = await revisions.create_candidate(
        agent, {"instruction": "Answer."}, message=None, origin="user", rationale=None,
        evidence=[],
    )
    _, suite = await _suite_with_cases(session, context, count=1)
    service = EvalRunService(session, context)
    assert await service.offline_passed(candidate.id) is False

    run = await service.create_run(suite.id, agent, baseline_revision_id=None,
                                   candidate_revision_id=candidate.id, trials=1, concurrency=1,
                                   budget_usd=Decimal("1"), allow_sandbox=False)
    for trial in await service.claim(run.id, limit=5):
        await service.record_outcome(trial.id, TrialOutcome(status="completed", response="answer"))
    await service.finalize(run.id)

    assert await service.offline_passed(candidate.id) is True
    assert uuid4() != candidate.id
