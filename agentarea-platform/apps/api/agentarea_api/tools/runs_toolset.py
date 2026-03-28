"""RunsToolset — start and manage agent execution runs."""

import json

from agentarea_agents_sdk.tools.decorator_tool import Toolset, tool_method

from .base import platform_context


class RunsToolset(Toolset):
    """Start, list, get, and cancel agent runs."""

    @tool_method
    async def start(self, agent_id: str, message: str) -> str:
        """Start a new agent run with the given message."""
        from uuid import UUID

        async with platform_context() as (
            session,
            user_ctx,
            repo_factory,
            event_broker,
            _,
        ):
            from agentarea_tasks.task_service import TaskService

            from agentarea_api.api.deps.services import _create_task_manager, get_temporal_workflow_service

            task_manager = await _create_task_manager(repo_factory)
            workflow_service = await get_temporal_workflow_service()
            service = TaskService(
                repository_factory=repo_factory,
                event_broker=event_broker,
                task_manager=task_manager,
                workflow_service=workflow_service,
            )
            task = await service.create_task_from_params(
                title=message[:100],
                description=message,
                query=message,
                user_id=user_ctx.user_id,
                agent_id=UUID(agent_id),
                workspace_id=user_ctx.workspace_id,
            )
            submitted = await service.submit_task(task)
            return json.dumps(
                {"run_id": str(submitted.id), "status": submitted.status},
                default=str,
            )

    @tool_method
    async def list(self, agent_id: str = "", limit: int = 20) -> str:
        """List recent runs, optionally filtered by agent ID."""
        async with platform_context() as (
            session,
            user_ctx,
            repo_factory,
            event_broker,
            _,
        ):
            from agentarea_tasks.task_service import TaskService

            from agentarea_api.api.deps.services import _create_task_manager, get_temporal_workflow_service

            task_manager = await _create_task_manager(repo_factory)
            workflow_service = await get_temporal_workflow_service()
            service = TaskService(
                repository_factory=repo_factory,
                event_broker=event_broker,
                task_manager=task_manager,
                workflow_service=workflow_service,
            )
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
        from uuid import UUID

        async with platform_context() as (
            session,
            user_ctx,
            repo_factory,
            event_broker,
            _,
        ):
            from agentarea_tasks.task_service import TaskService

            from agentarea_api.api.deps.services import _create_task_manager, get_temporal_workflow_service

            task_manager = await _create_task_manager(repo_factory)
            workflow_service = await get_temporal_workflow_service()
            service = TaskService(
                repository_factory=repo_factory,
                event_broker=event_broker,
                task_manager=task_manager,
                workflow_service=workflow_service,
            )
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
        from uuid import UUID

        async with platform_context() as (
            session,
            user_ctx,
            repo_factory,
            event_broker,
            _,
        ):
            from agentarea_tasks.task_service import TaskService

            from agentarea_api.api.deps.services import _create_task_manager, get_temporal_workflow_service

            task_manager = await _create_task_manager(repo_factory)
            workflow_service = await get_temporal_workflow_service()
            service = TaskService(
                repository_factory=repo_factory,
                event_broker=event_broker,
                task_manager=task_manager,
                workflow_service=workflow_service,
            )
            cancelled = await service.cancel_task(UUID(run_id))
            return json.dumps({"cancelled": cancelled})
