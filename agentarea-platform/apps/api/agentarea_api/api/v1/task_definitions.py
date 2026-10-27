"""Saved tasks: the description of a task -- agent, text, parameters -- run on demand.

A trigger may point at one instead of carrying its own text; a run records the
definition it came from.
"""

import logging
from typing import Annotated, Any
from uuid import UUID

from agentarea_api.api.deps.services import get_task_definition_service
from agentarea_common.agent_status import AgentArchivedError
from agentarea_common.auth.dependencies import UserContextDep
from agentarea_common.auth.route_authz import enforced_in_handler, requires, unrestricted
from agentarea_common.utils.types import UtcDatetime
from agentarea_governance.domain.policies import PolicyValidationError
from agentarea_tasks.application.task_definition_service import TaskDefinitionService
from agentarea_tasks.domain.exceptions import AgentModelNotConfiguredError
from agentarea_tasks.domain.task_definitions import (
    TaskDefinition,
    TaskDefinitionInUseError,
    TaskDefinitionNotFoundError,
    TaskDefinitionValidationError,
)
from agentarea_tasks.schemas.dto import (
    TaskDefinitionCreate,
    TaskDefinitionRun,
    TaskDefinitionUpdate,
)
from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel

from .agents_tasks import TaskResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/task-definitions", tags=["task-definitions"])

TaskDefinitionServiceDep = Annotated[TaskDefinitionService, Depends(get_task_definition_service)]


class TaskDefinitionResponse(BaseModel):
    id: UUID
    name: str
    description: str
    agent_id: UUID
    parameters: dict[str, Any]
    created_by: str
    created_at: UtcDatetime
    updated_at: UtcDatetime

    @classmethod
    def from_domain(cls, definition: TaskDefinition) -> TaskDefinitionResponse:
        return cls.model_validate(definition.model_dump())


@router.get(
    "/",
    response_model=list[TaskDefinitionResponse],
    dependencies=[
        unrestricted("workspace member; the workspace-scoped repository is the boundary")
    ],
)
async def list_task_definitions(
    service: TaskDefinitionServiceDep,
    agent_id: UUID | None = Query(None, description="Only this agent's saved tasks"),
    limit: int = Query(100, ge=1, le=1000, description="Most saved tasks to return"),
) -> list[TaskDefinitionResponse]:
    """List the workspace's saved tasks, newest first."""
    definitions = await service.list(agent_id=agent_id, limit=limit)
    return [TaskDefinitionResponse.from_domain(d) for d in definitions]


@router.post(
    "/",
    response_model=TaskDefinitionResponse,
    status_code=201,
    dependencies=[
        unrestricted("workspace member; the workspace-scoped repository is the boundary")
    ],
)
async def create_task_definition(
    service: TaskDefinitionServiceDep,
    payload: TaskDefinitionCreate = Body(...),
) -> TaskDefinitionResponse:
    """Save a task: the agent, what to ask it, and the parameters."""
    try:
        definition = await service.create(payload)
    except TaskDefinitionValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return TaskDefinitionResponse.from_domain(definition)


@router.get(
    "/{definition_id}",
    response_model=TaskDefinitionResponse,
    dependencies=[
        unrestricted("workspace member; the workspace-scoped repository is the boundary")
    ],
)
async def get_task_definition(
    definition_id: UUID, service: TaskDefinitionServiceDep
) -> TaskDefinitionResponse:
    """Get a saved task."""
    try:
        return TaskDefinitionResponse.from_domain(await service.get(definition_id))
    except TaskDefinitionNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.put(
    "/{definition_id}",
    response_model=TaskDefinitionResponse,
    dependencies=[requires("edit", "task_definition", id_param="definition_id")],
)
async def update_task_definition(
    definition_id: UUID,
    service: TaskDefinitionServiceDep,
    payload: TaskDefinitionUpdate = Body(...),
) -> TaskDefinitionResponse:
    """Change a saved task; only the fields sent change."""
    try:
        return TaskDefinitionResponse.from_domain(await service.update(definition_id, payload))
    except TaskDefinitionNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except TaskDefinitionValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except TaskDefinitionInUseError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e


@router.delete(
    "/{definition_id}",
    status_code=204,
    dependencies=[requires("delete", "task_definition", id_param="definition_id")],
)
async def delete_task_definition(definition_id: UUID, service: TaskDefinitionServiceDep) -> None:
    """Delete a saved task no trigger runs. Runs started from it stay."""
    try:
        deleted = await service.delete(definition_id)
    except TaskDefinitionInUseError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Task definition {definition_id} not found")


@router.post(
    "/{definition_id}/run",
    response_model=TaskResponse,
    status_code=201,
    dependencies=[
        enforced_in_handler(
            "execute on the saved task's agent, known once it is loaded; "
            "TaskDefinitionService.run checks it"
        )
    ],
)
async def run_task_definition(
    definition_id: UUID,
    service: TaskDefinitionServiceDep,
    user_context: UserContextDep,
    payload: TaskDefinitionRun | None = Body(None),
) -> TaskResponse:
    """Run a saved task now with its agent, text and parameters; the run acts as the agent.

    ``parameters`` in the body are merged over the saved ones for this run only.
    """
    try:
        task = await service.run(
            definition_id, parameters=payload.parameters if payload is not None else None
        )
    except TaskDefinitionNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except PolicyValidationError as e:
        raise HTTPException(status_code=422, detail="Task policy rejected") from e
    except AgentModelNotConfiguredError as e:
        raise HTTPException(status_code=422, detail="Agent model is not configured") from e
    except AgentArchivedError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except ValueError as e:
        logger.error("Agent validation failed for task definition %s", definition_id, exc_info=True)
        raise HTTPException(status_code=404, detail="Agent validation error") from e
    return TaskResponse.from_agent_task(task, user_context)
