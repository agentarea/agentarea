"""Decide which revision a new run executes.

Called once, where a task is persisted. The answer is the agent's serving
revision, or an experiment arm when one is running. The task keeps it for its
whole life, so follow-ups, retries and continuations run the same revision.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from agentarea_common.auth.context import UserContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agentarea_agents.domain.models import Agent
from agentarea_agents.serving.assignment import ARM_CANDIDATE, pick_arm
from agentarea_agents.serving.models import EXPERIMENT_RUNNING, EXPERIMENT_STOPPED, AgentExperiment
from agentarea_agents.serving.revision_service import RevisionService


@dataclass(frozen=True)
class RunPin:
    revision_id: UUID
    experiment_id: UUID | None = None
    arm: str | None = None


async def running_experiment(session: AsyncSession, agent_id: UUID) -> AgentExperiment | None:
    result = await session.execute(
        select(AgentExperiment).where(
            AgentExperiment.agent_id == agent_id, AgentExperiment.status == EXPERIMENT_RUNNING
        )
    )
    return result.scalar_one_or_none()


class RunPinner:
    def __init__(self, session: AsyncSession, user_context: UserContext):
        self.session = session
        self.revisions = RevisionService(session, user_context)

    async def pin(self, agent: Agent, task_id: UUID) -> RunPin:
        current = await self.revisions.ensure_current(agent, origin="detected")
        experiment = await running_experiment(self.session, agent.id)
        if experiment is None:
            return RunPin(revision_id=current.id)

        if experiment.control_revision_id != current.id:
            # What serves changed under the experiment; its comparison is void.
            experiment.status = EXPERIMENT_STOPPED
            experiment.stop_reason = "stale"
            experiment.ended_at = datetime.now(UTC)
            await self.session.commit()
            return RunPin(revision_id=current.id)

        arm = pick_arm(str(task_id), experiment.weights)
        revision_id = (
            experiment.candidate_revision_id
            if arm == ARM_CANDIDATE
            else experiment.control_revision_id
        )
        return RunPin(revision_id=revision_id, experiment_id=experiment.id, arm=arm)
