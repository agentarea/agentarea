"""RunsToolset — start, list, get, and cancel agent execution runs.

Tool method signatures are explicit kwargs (MCP-idiomatic flat wire schema)
but the source of truth for ``start`` is the Pydantic DTO ``RunCreate`` in
``agentarea_tasks.schemas.dto``. The contract test in
``tests/unit/test_mcp_rest_parity.py`` enforces parity between toolset
kwargs and DTO fields.
"""

import json
from typing import Any
from uuid import UUID

from agentarea_agents_sdk.tools.decorator_tool import Toolset, tool_method
from agentarea_agents_sdk.tools.tool_definition import toolset
from agentarea_tasks.schemas.dto import RunCreate
from agentarea_tasks.task_service import TaskService

from agentarea_api.api.deps.services import (
    _create_task_manager,
    get_temporal_workflow_service,
)

from .base import platform_context, platform_read_context


async def _build_task_service(repo_factory, event_broker) -> TaskService:
    """Build a TaskService bound to the request-scoped repo factory."""
    task_manager = await _create_task_manager(repo_factory)
    workflow_service = await get_temporal_workflow_service()
    return TaskService(
        repository_factory=repo_factory,
        event_broker=event_broker,
        task_manager=task_manager,
        workflow_service=workflow_service,
    )


@toolset(
    namespace="agentarea/runs",
    display_name="Agent Runs",
    description="Start, monitor, and manage agent execution runs.",
    category="platform",
)
class RunsToolset(Toolset):
    """Start, list, get, and cancel agent runs."""

    @tool_method
    async def start(
        self,
        agent_id: str,
        description: str,
        parameters: dict[str, Any] | None = None,
        requires_human_approval: bool = False,
        project_id: str | None = None,
    ) -> str:
        """Start a new agent run.

        Routes through ``TaskService.start_run`` so REST, MCP and A2A share the
        same execution path (channel routing, metadata defaults, workflow
        submission). Kwargs mirror the ``RunCreate`` REST DTO.
        """
        payload = RunCreate(
            agent_id=UUID(agent_id),
            description=description,
            parameters=parameters or {},
            requires_human_approval=requires_human_approval,
            project_id=project_id,
        )

        async with platform_context() as (
            _session,
            user_ctx,
            repo_factory,
            event_broker,
            _,
        ):
            service = await _build_task_service(repo_factory, event_broker)
            submitted = await service.start_run(
                payload,
                workspace_id=user_ctx.workspace_id,
                user_id=user_ctx.user_id,
                created_via="mcp",
            )
            return json.dumps(
                {"run_id": str(submitted.id), "status": submitted.status},
                default=str,
            )

    @tool_method
    async def list(self, agent_id: str = "", limit: int = 20) -> str:
        """List recent runs, optionally filtered by agent ID."""
        async with platform_read_context() as (
            _session,
            user_ctx,
            repo_factory,
            event_broker,
            _,
        ):
            service = await _build_task_service(repo_factory, event_broker)
            tasks = await service.list_tasks(user_id=user_ctx.user_id, limit=limit)
            return json.dumps(
                [
                    {
                        "run_id": str(t.id),
                        "title": t.title,
                        "status": t.status,
                        "agent_id": str(t.agent_id) if t.agent_id else None,
                    }
                    for t in tasks
                ],
                default=str,
            )

    @tool_method
    async def get(self, run_id: str) -> str:
        """Get status and details of a specific run."""
        async with platform_read_context() as (
            _session,
            _user_ctx,
            repo_factory,
            event_broker,
            _,
        ):
            service = await _build_task_service(repo_factory, event_broker)
            task = await service.get_task(UUID(run_id))
            if not task:
                return json.dumps({"error": "Run not found"})
            return json.dumps(
                {
                    "run_id": str(task.id),
                    "title": task.title,
                    "status": task.status,
                    "agent_id": str(task.agent_id) if task.agent_id else None,
                    "query": task.query,
                },
                default=str,
            )

    @tool_method
    async def cancel(self, run_id: str) -> str:
        """Cancel a running agent execution."""
        async with platform_context() as (
            _session,
            _user_ctx,
            repo_factory,
            event_broker,
            _,
        ):
            service = await _build_task_service(repo_factory, event_broker)
            cancelled = await service.cancel_task(UUID(run_id))
            return json.dumps({"cancelled": cancelled})
