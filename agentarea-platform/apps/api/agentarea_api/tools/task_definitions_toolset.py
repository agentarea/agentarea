"""TaskDefinitionsToolset — saved tasks: list, get, create, and run one now.

Kwargs mirror ``TaskDefinitionCreate`` in ``agentarea_tasks.schemas.dto``; a run
goes through ``TaskDefinitionService.run``, as ``POST .../task-definitions/{id}/run``.
"""

import json
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from agentarea_agents_sdk.tools.base_tool import ToolError
from agentarea_agents_sdk.tools.decorator_tool import Toolset, tool_method
from agentarea_agents_sdk.tools.tool_authz import enforced_in_handler, unrestricted
from agentarea_agents_sdk.tools.tool_definition import toolset
from agentarea_tasks.application.task_definition_service import TaskDefinitionService
from agentarea_tasks.domain.exceptions import AgentModelNotConfiguredError, BudgetCapExceededError
from agentarea_tasks.domain.task_definitions import (
    TaskDefinition,
    TaskDefinitionNotFoundError,
    TaskDefinitionValidationError,
)
from agentarea_tasks.schemas.dto import TaskDefinitionCreate
from fastapi import HTTPException
from pydantic import BaseModel, Field

from .base import platform_context, platform_read_context
from .runs_toolset import RunStarted, _build_task_service

DefinitionId = Annotated[
    str, Field(description="Saved task id (UUID), from `task_definitions_list`.")
]


class TaskDefinitionOutput(BaseModel):
    id: str = Field(description="Saved task id (UUID).")
    name: str = Field(description="What the saved task is called.")
    description: str = Field(description="What the agent is asked each time it runs.")
    agent_id: str = Field(description="Id (UUID) of the agent that runs it.")
    parameters: dict[str, Any] = Field(description="Task parameters every run starts with.")
    created_by: str = Field(description="Who saved it.")
    updated_at: datetime = Field(description="When it last changed.")


def _output(definition: TaskDefinition) -> dict[str, Any]:
    return {
        "id": str(definition.id),
        "name": definition.name,
        "description": definition.description,
        "agent_id": str(definition.agent_id),
        "parameters": definition.parameters,
        "created_by": definition.created_by,
        "updated_at": definition.updated_at,
    }


async def _service(repo_factory: Any, broker: Any) -> TaskDefinitionService:
    return TaskDefinitionService(repo_factory, await _build_task_service(repo_factory, broker))


@toolset(
    namespace="agentarea/task_definitions",
    display_name="Saved tasks",
    description="Save what to ask an agent, and run it on demand or from a trigger.",
    category="platform",
    plane="operate",
)
class TaskDefinitionsToolset(Toolset):
    """List, get, create and run saved tasks."""

    open_world = False

    @tool_method(display_name="List saved tasks", effect="read", output=list[TaskDefinitionOutput])
    @unrestricted("saved tasks in the caller's workspace, as GET /v1/task-definitions lists them")
    async def list(
        self,
        agent_id: Annotated[
            str, Field(description="Only this agent's saved tasks (UUID); empty for all.")
        ] = "",
        limit: Annotated[
            int, Field(ge=1, le=1000, description="Most saved tasks to return.")
        ] = 100,
    ) -> str:
        """List the workspace's saved tasks, newest first."""
        async with platform_read_context() as (_session, _user_ctx, repo_factory, broker, _secret):
            service = await _service(repo_factory, broker)
            definitions = await service.list(
                agent_id=UUID(agent_id) if agent_id else None, limit=limit
            )
            return json.dumps([_output(d) for d in definitions], default=str)

    @tool_method(display_name="Get saved task", effect="read", output=TaskDefinitionOutput)
    @unrestricted("a saved task in the caller's workspace, as GET /v1/task-definitions/{id}")
    async def get(self, definition_id: DefinitionId) -> str:
        """Get a saved task by id."""
        async with platform_read_context() as (_session, _user_ctx, repo_factory, broker, _secret):
            service = await _service(repo_factory, broker)
            try:
                definition = await service.get(UUID(definition_id))
            except TaskDefinitionNotFoundError as exc:
                raise ToolError(str(exc)) from None
            return json.dumps(_output(definition), default=str)

    @tool_method(display_name="Create saved task", effect="write", output=TaskDefinitionOutput)
    @unrestricted("any member may save a task, as POST /v1/task-definitions allows")
    async def create(
        self,
        name: Annotated[str, Field(description="What the saved task is called; 1-255 characters.")],
        agent_id: Annotated[str, Field(description="Agent id (UUID), from `agents_list`.")],
        description: Annotated[
            str, Field(description="What the agent is asked to do each time it runs.")
        ],
        parameters: Annotated[
            dict[str, Any] | None,
            Field(description="Task parameters every run starts with, as for `runs_start`."),
        ] = None,
    ) -> str:
        """Save a task: an agent, what to ask it, and the parameters.

        Run it with `task_definitions_run`, or point a trigger at it with
        `task_definition_id` so each firing asks this.
        """
        payload = TaskDefinitionCreate(
            name=name,
            agent_id=UUID(agent_id),
            description=description,
            parameters=parameters or {},
        )
        async with platform_context() as (_session, _user_ctx, repo_factory, broker, _secret):
            service = await _service(repo_factory, broker)
            try:
                definition = await service.create(payload)
            except TaskDefinitionValidationError as exc:
                raise ToolError(str(exc)) from None
            return json.dumps(_output(definition), default=str)

    @tool_method(display_name="Run saved task", effect="write", output=RunStarted)
    @enforced_in_handler(
        "execute on the saved task's agent, known once it is loaded; "
        "TaskDefinitionService.run checks it"
    )
    async def run(
        self,
        definition_id: DefinitionId,
        parameters: Annotated[
            dict[str, Any] | None,
            Field(description="Merged over the saved task's own parameters for this run only."),
        ] = None,
    ) -> str:
        """Run a saved task now (it acts as its agent); returns the run to watch with `runs_get`."""
        async with platform_context() as (_session, _user_ctx, repo_factory, broker, _secret):
            service = await _service(repo_factory, broker)
            try:
                task = await service.run(
                    UUID(definition_id), parameters=parameters, created_via="mcp"
                )
            except HTTPException as exc:
                raise ToolError(str(exc.detail)) from None
            except (
                TaskDefinitionNotFoundError,
                AgentModelNotConfiguredError,
                BudgetCapExceededError,
            ) as exc:
                raise ToolError(str(exc)) from None
            return json.dumps(
                {"run_id": str(task.id), "status": task.status, "scheduled_at": task.scheduled_at},
                default=str,
            )
