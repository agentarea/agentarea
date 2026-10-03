"""Record, propose and activate agent revisions.

The agent's executable columns are the materialized copy of the revision its
``current_revision_id`` points at. Whoever writes those columns, the next
:meth:`RevisionService.ensure_current` notices the hash moved and records a
revision, so a run is always pinned to something real even when a writer
bypassed this service.
"""

from typing import Any
from uuid import UUID

from agentarea_common.auth.context import UserContext
from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from agentarea_agents.domain.models import Agent
from agentarea_agents.domain.skill_models import agent_skills_table
from agentarea_agents.serving.models import (
    REVISION_ACTIVE,
    REVISION_ARCHIVED,
    REVISION_CANDIDATE,
    AgentRevision,
)
from agentarea_agents.serving.repository import AgentRevisionRepository
from agentarea_agents.serving.revision_spec import RevisionSpec, apply_patch


class RevisionNotFoundError(LookupError):
    pass


class StaleRevisionError(ValueError):
    """A candidate proposed against a revision that no longer serves."""


class UnchangedRevisionError(ValueError):
    """A candidate that would run exactly what already serves."""


class RevisionService:
    def __init__(self, session: AsyncSession, user_context: UserContext):
        self.session = session
        self.user_context = user_context
        self.repository = AgentRevisionRepository(session, user_context)

    async def list_revisions(self, agent_id: UUID) -> list[AgentRevision]:
        return await self.repository.list_for_agent(agent_id)

    async def get(self, agent_id: UUID, revision_id: UUID) -> AgentRevision | None:
        return await self.repository.get_for_agent(agent_id, revision_id)

    def is_stale(self, revision: AgentRevision, agent: Agent) -> bool:
        return (
            revision.status == REVISION_CANDIDATE
            and revision.parent_revision_id != agent.current_revision_id
        )

    async def ensure_current(self, agent: Agent, *, origin: str) -> AgentRevision:
        """Return the revision matching the agent's columns, recording one if needed."""
        spec = RevisionSpec.from_agent(agent, await self._skill_ids(agent.id))
        digest = spec.config_hash()
        current = await self._current(agent)
        if current is not None and current.config_hash == digest:
            return current

        await self._lock(agent)
        current = await self._current(agent)
        if current is not None and current.config_hash == digest:
            return current

        revision = self._new_revision(
            agent,
            spec,
            number=await self.repository.next_number(agent.id),
            parent=current,
            status=REVISION_ACTIVE,
            origin=origin,
        )
        if current is not None:
            current.status = REVISION_ARCHIVED
        await self.session.flush()
        agent.current_revision_id = revision.id
        await self.session.commit()
        return revision

    async def create_candidate(
        self,
        agent: Agent,
        patch: dict[str, Any],
        *,
        message: str | None,
        origin: str,
        rationale: str | None,
        evidence: list[dict[str, Any]],
    ) -> AgentRevision:
        base = await self.ensure_current(agent, origin="detected")
        spec = apply_patch(RevisionSpec.from_dict(base.spec), patch)
        if spec.config_hash() == base.config_hash:
            raise UnchangedRevisionError("the candidate runs exactly what already serves")

        await self._lock(agent)
        revision = self._new_revision(
            agent,
            spec,
            number=await self.repository.next_number(agent.id),
            parent=base,
            status=REVISION_CANDIDATE,
            origin=origin,
            message=message,
            rationale=rationale,
            evidence=evidence,
        )
        await self.session.commit()
        return revision

    async def activate(self, agent: Agent, revision_id: UUID) -> AgentRevision:
        """Make ``revision_id`` the serving revision and copy its spec onto the agent.

        An archived revision is a rollback and always allowed. A candidate is
        refused once the revision it was proposed against stopped serving.
        """
        revision = await self.repository.get_for_agent(agent.id, revision_id)
        if revision is None:
            raise RevisionNotFoundError(f"revision {revision_id} not found for agent {agent.id}")
        if revision.id == agent.current_revision_id:
            return revision

        await self._lock(agent)
        if self.is_stale(revision, agent):
            raise StaleRevisionError(
                f"revision {revision.number} was proposed against a revision that no longer serves"
            )

        spec = RevisionSpec.from_dict(revision.spec)
        agent.instruction = spec.instruction
        agent.model_id = spec.model_id
        agent.tools = list(spec.tools)
        agent.planning = spec.planning
        agent.a2ui_enabled = spec.a2ui_enabled
        await self.session.execute(
            delete(agent_skills_table).where(agent_skills_table.c.agent_id == agent.id)
        )
        if spec.skill_ids:
            await self.session.execute(
                insert(agent_skills_table),
                [{"agent_id": agent.id, "skill_id": UUID(s)} for s in spec.skill_ids],
            )

        current = await self._current(agent)
        if current is not None:
            current.status = REVISION_ARCHIVED
        revision.status = REVISION_ACTIVE
        agent.current_revision_id = revision.id
        await self.session.commit()
        return revision

    async def _current(self, agent: Agent) -> AgentRevision | None:
        if agent.current_revision_id is None:
            return None
        return await self.repository.get_for_agent(agent.id, agent.current_revision_id)

    async def _lock(self, agent: Agent) -> None:
        """Serialize pointer moves for one agent and re-read its pointer."""
        result = await self.session.execute(
            select(Agent.current_revision_id).where(Agent.id == agent.id).with_for_update()
        )
        agent.current_revision_id = result.scalar_one()

    async def _skill_ids(self, agent_id: UUID) -> list[str]:
        result = await self.session.execute(
            select(agent_skills_table.c.skill_id).where(agent_skills_table.c.agent_id == agent_id)
        )
        return [str(skill_id) for skill_id in result.scalars().all()]

    def _new_revision(
        self,
        agent: Agent,
        spec: RevisionSpec,
        *,
        number: int,
        parent: AgentRevision | None,
        status: str,
        origin: str,
        message: str | None = None,
        rationale: str | None = None,
        evidence: list[dict[str, Any]] | None = None,
    ) -> AgentRevision:
        revision = AgentRevision(
            agent_id=agent.id,
            number=number,
            parent_revision_id=parent.id if parent is not None else None,
            spec=spec.to_dict(),
            config_hash=spec.config_hash(),
            status=status,
            origin=origin,
            message=message,
            rationale=rationale,
            evidence=list(evidence or []),
            workspace_id=self.user_context.workspace_id,
            created_by=self.user_context.user_id,
        )
        self.session.add(revision)
        return revision
