"""Experiments against the real schema.

Set EVALS_TEST_DATABASE_URL (``make check-db`` does).
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import update
from agentarea_agents.serving.models import AgentExperiment
from agentarea_agents.serving.revision_service import RevisionService
from agentarea_evals.decisions.engine import ExperimentPolicy
from agentarea_evals.experiments.service import ExperimentError, ExperimentService

from .conftest import make_agent, make_tasks, needs_db

pytestmark = needs_db


class Activations:
    def __init__(self, session, context):
        self.calls = []
        self.revisions = RevisionService(session, context)
        self.agents = {}

    async def __call__(self, agent_id, revision_id):
        self.calls.append((agent_id, revision_id))
        await self.revisions.activate(self.agents[agent_id], revision_id)


async def _setup(session, context, *, offline_passed=True):
    agent = await make_agent(session, context)
    revisions = RevisionService(session, context)
    control = await revisions.ensure_current(agent, origin="create")
    candidate = await revisions.create_candidate(
        agent, {"instruction": "Help, briefly."}, message=None, origin="user",
        rationale=None, evidence=[],
    )
    activations = Activations(session, context)
    activations.agents[agent.id] = agent
    service = ExperimentService(
        session, context, activate=activations, offline_passed=lambda _c, _b: _offline(offline_passed)
    )
    return agent, control, candidate, service, activations


async def _offline(value):
    return value


async def test_start_splits_traffic_at_the_first_step(session, context):
    agent, control, candidate, service, _ = await _setup(session, context)

    experiment = await service.start(agent, candidate.id, ExperimentPolicy(auto_promote=True))

    assert experiment.status == "running"
    assert experiment.weights == {"control": 90, "candidate": 10}
    assert experiment.control_revision_id == control.id


async def test_only_one_experiment_runs_per_agent(session, context):
    agent, _, candidate, service, _ = await _setup(session, context)
    await service.start(agent, candidate.id, ExperimentPolicy(auto_promote=True))

    with pytest.raises(ExperimentError, match="already"):
        await service.start(agent, candidate.id, ExperimentPolicy(auto_promote=True))


async def test_the_serving_revision_cannot_be_its_own_candidate(session, context):
    agent, control, _, service, _ = await _setup(session, context)

    with pytest.raises(ExperimentError, match="candidate"):
        await service.start(agent, control.id, ExperimentPolicy(auto_promote=True))


async def test_a_regression_stops_the_experiment(session, context):
    agent, control, candidate, service, _ = await _setup(session, context)
    experiment = await service.start(agent, candidate.id, ExperimentPolicy(auto_promote=True))
    await make_tasks(session, context, agent, count=95, status="completed",
                     revision_id=control.id, experiment_id=experiment.id)
    await make_tasks(session, context, agent, count=5, status="failed",
                     revision_id=control.id, experiment_id=experiment.id)
    await make_tasks(session, context, agent, count=10, status="completed",
                     revision_id=candidate.id, experiment_id=experiment.id)
    await make_tasks(session, context, agent, count=10, status="failed",
                     revision_id=candidate.id, experiment_id=experiment.id)

    decision = await service.evaluate(experiment)

    assert decision.action == "stop"
    assert experiment.status == "stopped"
    assert experiment.stop_reason == "regression"
    assert experiment.decisions[-1]["action"] == "stop"


async def test_a_clean_step_ramps_the_candidate_share(session, context):
    agent, control, candidate, service, _ = await _setup(session, context)
    experiment = await service.start(agent, candidate.id, ExperimentPolicy(auto_promote=True))
    await make_tasks(session, context, agent, count=180, status="completed",
                     revision_id=control.id, experiment_id=experiment.id)
    await make_tasks(session, context, agent, count=20, status="failed",
                     revision_id=control.id, experiment_id=experiment.id)
    await make_tasks(session, context, agent, count=20, status="completed",
                     revision_id=candidate.id, experiment_id=experiment.id)

    decision = await service.evaluate(experiment)

    assert decision.action == "ramp"
    assert experiment.weights == {"control": 75, "candidate": 25}


async def test_a_non_inferior_candidate_at_full_exposure_is_promoted(session, context):
    agent, control, candidate, service, activations = await _setup(session, context)
    experiment = await service.start(
        agent, candidate.id, ExperimentPolicy(auto_promote=True, steps=(50,))
    )
    await make_tasks(session, context, agent, count=190, status="completed",
                     revision_id=control.id, experiment_id=experiment.id)
    await make_tasks(session, context, agent, count=10, status="failed",
                     revision_id=control.id, experiment_id=experiment.id)
    await make_tasks(session, context, agent, count=196, status="completed",
                     revision_id=candidate.id, experiment_id=experiment.id)
    await make_tasks(session, context, agent, count=4, status="failed",
                     revision_id=candidate.id, experiment_id=experiment.id)

    decision = await service.evaluate(experiment)

    assert decision.action == "promote"
    assert experiment.status == "promoted"
    assert activations.calls == [(agent.id, candidate.id)]
    assert agent.current_revision_id == candidate.id


async def test_without_an_offline_pass_promotion_is_only_recommended(session, context):
    agent, control, candidate, service, activations = await _setup(
        session, context, offline_passed=False
    )
    experiment = await service.start(
        agent, candidate.id, ExperimentPolicy(auto_promote=True, steps=(50,))
    )
    await make_tasks(session, context, agent, count=200, status="completed",
                     revision_id=control.id, experiment_id=experiment.id)
    await make_tasks(session, context, agent, count=200, status="completed",
                     revision_id=candidate.id, experiment_id=experiment.id)

    decision = await service.evaluate(experiment)

    assert decision.action == "recommend_promote"
    assert experiment.status == "running"
    assert activations.calls == []


async def test_manual_stop_and_promote(session, context):
    agent, _, candidate, service, activations = await _setup(session, context)
    experiment = await service.start(agent, candidate.id, ExperimentPolicy(auto_promote=False))

    await service.promote(experiment)

    assert experiment.status == "promoted"
    assert activations.calls == [(agent.id, candidate.id)]
    with pytest.raises(ExperimentError, match="running"):
        await service.stop(experiment)


async def test_evaluating_a_finished_experiment_does_nothing(session, context):
    agent, _, candidate, service, _ = await _setup(session, context)
    experiment = await service.start(agent, candidate.id, ExperimentPolicy(auto_promote=True))
    await service.stop(experiment)

    assert await service.evaluate(experiment) is None
    assert experiment.stop_reason == "manual"


async def test_an_expired_experiment_stops_inconclusive(session, context):
    agent, _, candidate, service, _ = await _setup(session, context)
    experiment = await service.start(agent, candidate.id, ExperimentPolicy(auto_promote=True))

    decision = await service.evaluate(experiment, now=datetime.now(UTC) + timedelta(days=60))

    assert decision.reason == "inconclusive"
    assert experiment.status == "stopped"


async def test_a_promotion_that_cannot_happen_stops_the_experiment(session, context):
    agent, control, candidate, service, _ = await _setup(session, context)

    async def refuse(_agent_id, _revision_id):
        raise PermissionError("the starter can no longer modify this agent")

    service.activate = refuse
    experiment = await service.start(
        agent, candidate.id, ExperimentPolicy(auto_promote=True, steps=(50,))
    )
    await make_tasks(session, context, agent, count=200, status="completed",
                     revision_id=control.id, experiment_id=experiment.id)
    await make_tasks(session, context, agent, count=200, status="completed",
                     revision_id=candidate.id, experiment_id=experiment.id)

    decision = await service.evaluate(experiment)

    assert decision.action == "stop"
    assert experiment.status == "stopped"
    assert experiment.stop_reason == "promotion_failed"
    assert agent.current_revision_id == control.id


async def test_a_stop_that_lands_first_wins_over_a_stale_copy(session, context):
    agent, _, candidate, service, activations = await _setup(session, context)
    experiment = await service.start(agent, candidate.id, ExperimentPolicy(auto_promote=False))
    # Another session stops it; this copy still says running.
    await session.execute(
        update(AgentExperiment)
        .where(AgentExperiment.id == experiment.id)
        .values(status="stopped", stop_reason="manual")
        .execution_options(synchronize_session=False)
    )
    assert experiment.status == "running"

    with pytest.raises(ExperimentError, match="running"):
        await service.promote(experiment)
    assert activations.calls == []
