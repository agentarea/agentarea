import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from agentarea_agents.application.agent_service import AgentService
from agentarea_agents.application.temporal_workflow_service import (
    TemporalWorkflowService,
)
from agentarea_api.api.deps.events import EventBrokerDep
from agentarea_api.api.deps.services import get_agent_service, get_temporal_workflow_service
from agentarea_tasks.domain.events import TaskCreated
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/agents/{agent_id}/tasks", tags=["agent-tasks"])


class TaskCreate(BaseModel):
    description: str
    parameters: dict[str, Any] = {}
    user_id: str | None = "api_user"
    enable_agent_communication: bool | None = True


class TaskResponse(BaseModel):
    id: UUID
    agent_id: UUID
    description: str
    parameters: dict[str, Any]
    status: str
    result: dict[str, Any] | None = None
    created_at: datetime
    execution_id: str | None = None  # Workflow execution ID

    @classmethod
    def create_new(
        cls,
        task_id: UUID,
        agent_id: UUID,
        description: str,
        parameters: dict[str, Any],
        execution_id: str | None = None,
    ) -> "TaskResponse":
        """Create a new task response for a newly created task."""
        return cls(
            id=task_id,
            agent_id=agent_id,
            description=description,
            parameters=parameters,
            status="running",  # Tasks are immediately running with workflows
            result=None,
            created_at=datetime.now(UTC),
            execution_id=execution_id,
        )


# Note: Old task manager approach has been replaced with Temporal workflows


@router.post("/", response_model=TaskResponse)
async def create_task_for_agent(
    agent_id: UUID,
    data: TaskCreate,
    event_broker: EventBrokerDep,
    agent_service: AgentService = Depends(get_agent_service),
    workflow_task_service: TemporalWorkflowService = Depends(
        get_temporal_workflow_service
    ),
):
    """Create and execute a task for the specified agent using Temporal workflows."""
    # Verify agent exists
    agent = await agent_service.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Generate a unique task ID
    task_id = uuid4()
    task_id_str = str(task_id)

    try:
        # Execute task using Temporal workflow - this returns immediately!
        result = await workflow_task_service.execute_agent_task_async(
            agent_id=agent_id,
            task_query=data.description,
            user_id=data.user_id or "api_user",
            task_parameters=data.parameters,
        )
        execution_id = result.get("execution_id")

        # Create the task response with execution ID
        task_response = TaskResponse.create_new(
            task_id=task_id,
            agent_id=agent_id,
            description=data.description,
            parameters=data.parameters,
            execution_id=execution_id,
        )

        # Create and publish TaskCreated event (for compatibility with existing event listeners)
        task_created_event = TaskCreated(
            task_id=task_id_str,
            agent_id=agent_id,
            description=data.description,
            parameters=data.parameters,
            metadata={
                "created_via": "api",
                "agent_name": agent.name,
                "created_at": task_response.created_at.isoformat(),
                "user_id": data.user_id,
                "enable_agent_communication": data.enable_agent_communication,
                "execution_id": execution_id,
            },
        )

        # Publish the event to the event broker
        await event_broker.publish(task_created_event)

        logger.info(
            f"Task {task_id_str} started with workflow execution ID "
            f"{execution_id} for agent {agent_id}"
        )

        return task_response

    except Exception as e:
        logger.error(f"Failed to start task workflow for agent {agent_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to start task: {e!s}") from e


@router.get("/", response_model=list[TaskResponse])
async def list_agent_tasks(
    agent_id: UUID,
    agent_service: AgentService = Depends(get_agent_service),
):
    """List all tasks for the specified agent."""
    # Verify agent exists
    agent = await agent_service.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Note: With Temporal workflows, task listing would require workflow history queries
    # For now, we return an empty list since individual task status can be checked
    # via /{task_id}/status
    # TODO: Implement workflow history querying to list agent tasks
    logger.info(
        f"Task listing requested for agent {agent_id}. "
        f"Use individual task status endpoints for workflow-based tasks."
    )

    return []


@router.get("/{task_id}", response_model=TaskResponse)
async def get_agent_task(
    agent_id: UUID,
    task_id: UUID,
    agent_service: AgentService = Depends(get_agent_service),
    workflow_task_service: TemporalWorkflowService = Depends(
        get_temporal_workflow_service
    ),
):
    """Get a specific task for the specified agent using workflow status."""
    # Verify agent exists
    agent = await agent_service.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    try:
        # Get workflow status using the execution ID pattern
        execution_id = f"agent-task-{task_id}"
        status = await workflow_task_service.get_workflow_status(execution_id)

        # If status indicates unknown, the task/workflow doesn't exist
        if status.get("status") == "unknown":
            raise HTTPException(status_code=404, detail="Task not found")

        # Convert workflow status to TaskResponse format
        task_response = TaskResponse(
            id=task_id,
            agent_id=agent_id,
            description="Workflow-based task",  # Description not stored in workflow status
            parameters={},  # Parameters not stored in workflow status
            status=status.get("status", "unknown"),
            result=status.get("result"),
            created_at=datetime.now(UTC),  # Could be extracted from start_time if available
            execution_id=execution_id,
        )

        return task_response

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get task: {e!s}") from e


@router.get("/{task_id}/status")
async def get_agent_task_status(
    agent_id: UUID,
    task_id: UUID,
    agent_service: AgentService = Depends(get_agent_service),
    workflow_task_service: TemporalWorkflowService = Depends(
        get_temporal_workflow_service
    ),
):
    """Get the execution status of a specific task workflow."""
    # Verify agent exists
    agent = await agent_service.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    try:
        # Get workflow status using the execution ID pattern
        execution_id = f"agent-task-{task_id}"
        status = await workflow_task_service.get_workflow_status(execution_id)

        return {
            "task_id": str(task_id),
            "agent_id": str(agent_id),
            "execution_id": execution_id,
            "status": status.get("status", "unknown"),
            "start_time": status.get("start_time"),
            "end_time": status.get("end_time"),
            "execution_time": status.get("execution_time"),
            "error": status.get("error"),
            "result": status.get("result"),
            # A2A-compatible fields for frontend
            "message": status.get("message"),
            "artifacts": status.get("artifacts"),
            "session_id": status.get("session_id"),
            "usage_metadata": status.get("usage_metadata"),
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get task status: {e!s}") from e


@router.delete("/{task_id}")
async def cancel_agent_task(
    agent_id: UUID,
    task_id: UUID,
    agent_service: AgentService = Depends(get_agent_service),
    workflow_task_service: TemporalWorkflowService = Depends(
        get_temporal_workflow_service
    ),
):
    """Cancel a specific task workflow for the specified agent."""
    # Verify agent exists
    agent = await agent_service.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    try:
        # Cancel the workflow using the execution ID pattern
        execution_id = f"agent-task-{task_id}"
        success = await workflow_task_service.cancel_task(execution_id)

        if success:
            return {"status": "cancelled", "task_id": str(task_id), "execution_id": execution_id}
        else:
            raise HTTPException(status_code=404, detail="Task not found or already completed")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to cancel task: {e!s}") from e
