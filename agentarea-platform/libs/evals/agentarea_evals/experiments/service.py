"""Start, evaluate and end traffic experiments between two revisions of an agent."""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from agentarea_agents.domain.models import Agent
from agentarea_agents.serving.assignment import ARM_CANDIDATE, ARM_CONTROL
from agentarea_agents.serving.models import (
    EXPERIMENT_PROMOTED,
    EXPERIMENT_RUNNING,
    EXPERIMENT_STOPPED,
    REVISION_CANDIDATE,
    AgentExperiment,
)
from agentarea_agents.serving.pinning import running_experiment
from agentarea_agents.serving.revision_service import RevisionService
from agentarea_common.auth.context import UserContext
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from agentarea_evals.decisions.engine import ArmStats, Decision, ExperimentPolicy, decide
from agentarea_evals.outcomes.stats import OutcomeStats

Activate = Callable[[UUID, UUID], Awaitable[Any]]
OfflineGate = Callable[[UUID], Awaitable[bool]]

_NO_RUNS = ArmStats(successes=0, failures=0)


class ExperimentError(ValueError):
    pass


class ExperimentService:
    """``activate`` serves a revision with the agent service's side effects;
    ``offline_passed`` says whether a candidate passed an offline evaluation.
    """

    def __init__(
        self,
        session: AsyncSession,
        user_context: UserContext,
        *,
        activate: Activate,
        offline_passed: OfflineGate,
    ):
        self.session = session
        self.user_context = user_context
        self.revisions = RevisionService(session, user_context)
        self.stats = OutcomeStats(session, user_context)
        self.activate = activate
        self.offline_passed = offline_passed

    async def list_for_agent(self, agent_id: UUID) -> list[AgentExperiment]:
        result = await self.session.execute(
            select(AgentExperiment)
            .where(
                AgentExperiment.agent_id == agent_id,
                AgentExperiment.workspace_id == self.user_context.workspace_id,
            )
            .order_by(AgentExperiment.started_at.desc())
        )
        return list(result.scalars().all())

    async def get(self, agent_id: UUID, experiment_id: UUID) -> AgentExperiment | None:
        result = await self.session.execute(
            select(AgentExperiment).where(
                AgentExperiment.id == experiment_id,
                AgentExperiment.agent_id == agent_id,
                AgentExperiment.workspace_id == self.user_context.workspace_id,
            )
        )
        return result.scalar_one_or_none()

    async def start(
        self, agent: Agent, candidate_revision_id: UUID, policy: ExperimentPolicy
    ) -> AgentExperiment:
        candidate = await self.revisions.get(agent.id, candidate_revision_id)
        if candidate is None:
            raise ExperimentError(f"revision {candidate_revision_id} not found for this agent")
        if candidate.status != REVISION_CANDIDATE:
            raise ExperimentError(f"revision {candidate.number} is not a candidate")
        current = await self.revisions.ensure_current(agent, origin="detected")
        if self.revisions.is_stale(candidate, agent):
            raise ExperimentError(
                f"revision {candidate.number} was proposed against a revision that no longer serves"
            )
        if await running_experiment(self.session, self.user_context, agent.id) is not None:
            raise ExperimentError("an experiment is already running for this agent")

        now = datetime.now(UTC)
        exposure = policy.steps[0]
        experiment = AgentExperiment(
            agent_id=agent.id,
            control_revision_id=current.id,
            candidate_revision_id=candidate.id,
            status=EXPERIMENT_RUNNING,
            weights={ARM_CONTROL: 100 - exposure, ARM_CANDIDATE: exposure},
            policy=policy.to_dict(),
            decisions=[{"at": now.isoformat(), "action": "start", "exposure": exposure}],
            started_at=now,
            workspace_id=self.user_context.workspace_id,
            created_by=self.user_context.user_id,
        )
        self.session.add(experiment)
        try:
            await self.session.commit()
        except IntegrityError as error:
            await self.session.rollback()
            raise ExperimentError("an experiment is already running for this agent") from error
        return experiment

    async def evaluate(
        self, experiment: AgentExperiment, *, now: datetime | None = None
    ) -> Decision | None:
        """Decide the experiment's next step from its runs so far and apply it."""
        if experiment.status != EXPERIMENT_RUNNING:
            return None
        now = now or datetime.now(UTC)
        policy = ExperimentPolicy.from_dict(experiment.policy)
        control, candidate = await self._arms(experiment)
        _, candidate_at_step = await self._arms(experiment, since=self._step_started(experiment))

        decision = decide(
            policy,
            exposure=experiment.weights[ARM_CANDIDATE],
            control=control,
            candidate=candidate,
            candidate_runs_at_step=candidate_at_step.runs,
            elapsed=now - experiment.started_at,
            offline_passed=await self.offline_passed(experiment.candidate_revision_id),
        )

        if decision.action == "ramp" and decision.exposure is not None:
            experiment.weights = {
                ARM_CONTROL: 100 - decision.exposure,
                ARM_CANDIDATE: decision.exposure,
            }
        elif decision.action == "stop":
            self._finish(experiment, EXPERIMENT_STOPPED, decision.reason, now)
        elif decision.action == "promote":
            await self.activate(experiment.agent_id, experiment.candidate_revision_id)
            self._finish(experiment, EXPERIMENT_PROMOTED, "auto", now)

        last_action = experiment.decisions[-1]["action"] if experiment.decisions else None
        if decision.action != "continue" and not (
            decision.action == "recommend_promote" and last_action == "recommend_promote"
        ):
            self._record(experiment, decision, control, candidate, now)
        experiment.last_evaluated_at = now
        await self.session.commit()
        return decision

    async def stop(self, experiment: AgentExperiment, *, reason: str = "manual") -> None:
        self._require_running(experiment)
        self._finish(experiment, EXPERIMENT_STOPPED, reason, datetime.now(UTC))
        await self.session.commit()

    async def promote(self, experiment: AgentExperiment) -> None:
        self._require_running(experiment)
        await self.activate(experiment.agent_id, experiment.candidate_revision_id)
        self._finish(experiment, EXPERIMENT_PROMOTED, "manual", datetime.now(UTC))
        await self.session.commit()

    async def arm_stats(self, experiment: AgentExperiment) -> tuple[ArmStats, ArmStats]:
        return await self._arms(experiment)

    async def _arms(
        self, experiment: AgentExperiment, *, since: datetime | None = None
    ) -> tuple[ArmStats, ArmStats]:
        outcomes = {
            outcome.revision_id: outcome.arm()
            for outcome in await self.stats.by_revision(
                experiment.agent_id,
                revision_ids=[experiment.control_revision_id, experiment.candidate_revision_id],
                experiment_id=experiment.id,
                since=since,
            )
        }
        return (
            outcomes.get(experiment.control_revision_id, _NO_RUNS),
            outcomes.get(experiment.candidate_revision_id, _NO_RUNS),
        )

    @staticmethod
    def _step_started(experiment: AgentExperiment) -> datetime:
        for entry in reversed(experiment.decisions or []):
            if entry.get("action") in ("start", "ramp"):
                return datetime.fromisoformat(entry["at"])
        return experiment.started_at

    @staticmethod
    def _require_running(experiment: AgentExperiment) -> None:
        if experiment.status != EXPERIMENT_RUNNING:
            raise ExperimentError(f"the experiment is {experiment.status}, not running")

    @staticmethod
    def _finish(experiment: AgentExperiment, status: str, reason: str, now: datetime) -> None:
        experiment.status = status
        experiment.stop_reason = reason
        experiment.ended_at = now

    @staticmethod
    def _record(
        experiment: AgentExperiment,
        decision: Decision,
        control: ArmStats,
        candidate: ArmStats,
        now: datetime,
    ) -> None:
        experiment.decisions = [
            *(experiment.decisions or []),
            {
                "at": now.isoformat(),
                "action": decision.action,
                "reason": decision.reason,
                "exposure": decision.exposure,
                "p_regression": decision.p_regression,
                "p_better": decision.p_better,
                "control": {"successes": control.successes, "failures": control.failures},
                "candidate": {"successes": candidate.successes, "failures": candidate.failures},
            },
        ]
