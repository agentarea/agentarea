"""Shared plumbing for the revision, experiment and evaluation routes."""

from contextlib import suppress
from typing import Any
from uuid import UUID

from agentarea_agents.application.agent_service import AgentService
from agentarea_agents.domain.models import Agent
from agentarea_common.auth.context import UserContext
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


def context_data(user_context: UserContext) -> dict[str, Any]:
    return {"user_id": user_context.user_id, "workspace_id": user_context.workspace_id}


async def start_workflow(name: str, workflow_id: str, args: dict[str, Any]) -> str:
    """Start an eval workflow on the worker's queue; a direct engine cannot run them."""
    settings = get_settings()
    if settings.workflow.EXECUTION_ENGINE == "direct":
        raise HTTPException(
            status_code=501,
            detail="This deployment's execution engine cannot run evaluations or experiments",
        )
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
