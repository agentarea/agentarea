"""Shared plumbing for the revision, experiment and evaluation routes."""

from contextlib import suppress
from typing import Any
from uuid import UUID

from agentarea_agents.application.agent_service import AgentService
from agentarea_agents.domain.models import Agent
from agentarea_agents.serving.revision_spec import RevisionSpec
from agentarea_common.auth.context import UserContext, UserPrincipal
from agentarea_common.auth.permission import require_permission
from agentarea_common.config import get_settings
from agentarea_common.workflow.executor import WorkflowConfig
from agentarea_common.workflow.temporal_executor import TemporalWorkflowExecutor
from fastapi import HTTPException


async def load_agent(
    agent_service: AgentService, identifier: str, user_context: UserContext, action: str
) -> Agent:
    """The tenant agent named by UUID or slug, once the graph allows ``action`` on it."""
    agent = None
    with suppress(ValueError):
        agent = await agent_service.get(UUID(identifier))
    if agent is None:
        agent = await agent_service.get_by_slug(identifier)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    await require_permission(action, "agent", str(agent.id), user_context.user_id)
    return agent


async def require_person_to_widen(
    agent_service: AgentService, agent: Agent, revision_id: UUID, principal: UserPrincipal
) -> None:
    """A candidate that lets the agent do more is served by a signed-in person.

    An API key (an agent or an integration) may propose one, but neither serve
    it nor start an experiment that promotes it on its own.
    """
    if principal.api_key_id is None:
        return
    revisions = agent_service.revisions()
    target = await revisions.get(agent.id, revision_id)
    current = (
        await revisions.get(agent.id, agent.current_revision_id)
        if agent.current_revision_id
        else None
    )
    if target is None or current is None:
        return
    if RevisionSpec.from_dict(target.spec).expands_capability_of(
        RevisionSpec.from_dict(current.spec)
    ):
        raise HTTPException(
            status_code=403,
            detail="This version lets the agent do more; a person must sign in to serve it",
        )


def context_data(user_context: UserContext) -> dict[str, Any]:
    return {"user_id": user_context.user_id, "workspace_id": user_context.workspace_id}


def require_workflow_engine() -> None:
    """Refuse before anything is written: a direct engine cannot run eval workflows."""
    if get_settings().workflow.EXECUTION_ENGINE == "direct":
        raise HTTPException(
            status_code=501,
            detail="This deployment's execution engine cannot run evaluations or experiments",
        )


async def start_workflow(name: str, workflow_id: str, args: dict[str, Any]) -> str:
    """Start an eval workflow on the worker's queue."""
    require_workflow_engine()
    settings = get_settings()
    executor = TemporalWorkflowExecutor(
        namespace=settings.workflow.TEMPORAL_NAMESPACE,
        server_url=settings.workflow.TEMPORAL_SERVER_URL,
    )
    return await executor.start_workflow(
        name,
        workflow_id,
        args,
        WorkflowConfig(task_queue=settings.workflow.TEMPORAL_TASK_QUEUE),
    )
