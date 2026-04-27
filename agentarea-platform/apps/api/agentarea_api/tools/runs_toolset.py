"""RunsToolset — start and manage agent execution runs."""

import json

from agentarea_agents_sdk.tools.decorator_tool import Toolset, tool_method

from .base import platform_context, platform_read_context


class RunsToolset(Toolset):
    """Start, list, get, and cancel agent runs."""

    @tool_method
    async def start(
        self,
        agent_id: str,
        message: str,
        parameters_json: str = "",
        enable_agent_communication: bool = True,
        requires_human_approval: bool = False,
    ) -> str:
        """Start a new agent run with the given message.

        Routes through ``TaskService.create_and_execute_task_with_workflow`` so
        REST, MCP and A2A share the same execution path. Optional knobs:

        - ``parameters_json``: JSON-encoded task parameters dict (e.g. for
          ``channel_origin`` routing or model overrides).
        - ``enable_agent_communication``: allow agent-to-agent calls (default True).
        - ``requires_human_approval``: gate the task on human approval (default False).
        """
        from uuid import UUID

        async with platform_context() as (
            _session,
            user_ctx,
            repo_factory,
            event_broker,
            _,
        ):
            from agentarea_tasks.task_service import TaskService

            from agentarea_api.api.deps.services import (
                _create_task_manager,
                get_temporal_workflow_service,
            )

            parameters: dict = {}
            if parameters_json:
                try:
                    parsed = json.loads(parameters_json)
                except json.JSONDecodeError as exc:
                    return json.dumps({"error": f"parameters_json must be valid JSON: {exc}"})
                if not isinstance(parsed, dict):
                    return json.dumps({"error": "parameters_json must decode to an object"})
                parameters = parsed

            task_manager = await _create_task_manager(repo_factory)
            workflow_service = await get_temporal_workflow_service()
            service = TaskService(
                repository_factory=repo_factory,
                event_broker=event_broker,
                task_manager=task_manager,
                workflow_service=workflow_service,
            )
            submitted = await service.create_and_execute_task_with_workflow(
                agent_id=UUID(agent_id),
                description=message,
                workspace_id=user_ctx.workspace_id,
                parameters=parameters,
                user_id=user_ctx.user_id,
                enable_agent_communication=enable_agent_communication,
                requires_human_approval=requires_human_approval,
                title=message[:100],
                metadata_overrides={"created_via": "mcp"},
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
            from agentarea_tasks.task_service import TaskService

            from agentarea_api.api.deps.services import (
                _create_task_manager,
                get_temporal_workflow_service,
            )

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

        async with platform_read_context() as (
            _session,
            _user_ctx,
            repo_factory,
            event_broker,
            _,
        ):
            from agentarea_tasks.task_service import TaskService

            from agentarea_api.api.deps.services import (
                _create_task_manager,
                get_temporal_workflow_service,
            )

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
            _session,
            _user_ctx,
            repo_factory,
            event_broker,
            _,
        ):
            from agentarea_tasks.task_service import TaskService

            from agentarea_api.api.deps.services import (
                _create_task_manager,
                get_temporal_workflow_service,
            )

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
