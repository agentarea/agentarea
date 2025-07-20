import logging
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from agentarea_agents.application.agent_service import AgentService
from agentarea_agents.application.temporal_workflow_service import (
    TemporalWorkflowService,
)
from agentarea_api.api.deps.services import (
    get_agent_service,
    get_task_service,
    get_temporal_workflow_service,
)
from agentarea_tasks.task_service import TaskService
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/agents/{agent_id}/tasks", tags=["agent-tasks"])

# Global tasks router (not agent-specific)
global_tasks_router = APIRouter(prefix="/tasks", tags=["tasks"])


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


class TaskWithAgent(BaseModel):
    """Task response with agent information for global task listing."""

    id: UUID
    agent_id: UUID
    agent_name: str
    description: str
    parameters: dict[str, Any]
    status: str
    result: dict[str, Any] | None = None
    created_at: datetime
    execution_id: str | None = None

    @classmethod
    def from_task_response(cls, task: TaskResponse, agent_name: str) -> "TaskWithAgent":
        """Create TaskWithAgent from TaskResponse and agent name."""
        return cls(
            id=task.id,
            agent_id=task.agent_id,
            agent_name=agent_name,
            description=task.description,
            parameters=task.parameters,
            status=task.status,
            result=task.result,
            created_at=task.created_at,
            execution_id=task.execution_id,
        )


@global_tasks_router.get("/", response_model=list[TaskWithAgent])
async def get_all_tasks(
    status: str | None = Query(None, description="Filter by task status"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of tasks to return"),
    offset: int = Query(0, ge=0, description="Number of tasks to skip"),
    agent_service: AgentService = Depends(get_agent_service),
    task_service: TaskService = Depends(get_task_service),
):
    """Get all tasks across all agents with optional filtering."""
    try:
        # Get all agents first
        agents = await agent_service.list()

        all_tasks: list[TaskWithAgent] = []

        # For each agent, get their tasks from service
        for agent in agents:
            try:
                # Get tasks with workflow status from service
                agent_tasks = await task_service.list_agent_tasks_with_workflow_status(agent.id, limit=limit)

                logger.info(f"Found {len(agent_tasks)} tasks for agent {agent.id} ({agent.name})")

                # Convert service tasks to TaskWithAgent format
                for task in agent_tasks:
                    # Create TaskWithAgent from service task
                    task_with_agent = TaskWithAgent(
                        id=task.id,
                        agent_id=task.agent_id,
                        agent_name=agent.name,
                        description=task.description,
                        parameters=task.task_parameters,
                        status=task.status,
                        result=task.result,
                        created_at=task.created_at,
                        execution_id=task.execution_id,
                    )
                    all_tasks.append(task_with_agent)

            except Exception as e:
                logger.warning(f"Failed to get tasks for agent {agent.id}: {e}")
                continue

        # Apply status filtering if specified
        if status:
            all_tasks = [task for task in all_tasks if task.status.lower() == status.lower()]

        # Sort by created_at descending (newest first)
        all_tasks.sort(key=lambda x: x.created_at, reverse=True)

        # Apply pagination
        paginated_tasks = all_tasks[offset : offset + limit]

        logger.info(f"Returning {len(paginated_tasks)} tasks out of {len(all_tasks)} total tasks")

        return paginated_tasks

    except Exception as e:
        logger.error(f"Failed to get all tasks: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to retrieve tasks: {e!s}") from e


class TaskEvent(BaseModel):
    """Model for task execution events."""

    id: str
    task_id: str
    agent_id: str
    execution_id: str
    timestamp: datetime
    event_type: str
    message: str
    metadata: dict[str, Any] = {}


class TaskEventResponse(BaseModel):
    """Response model for paginated task events."""

    events: list[TaskEvent]
    total: int
    page: int
    page_size: int
    has_next: bool


class TaskSSEEvent(BaseModel):
    """Model for Server-Sent Events."""

    type: str
    data: dict[str, Any]


# Use the proper task service from dependency injection


# Note: Old task manager approach has been replaced with Temporal workflows


@router.post("/", response_model=TaskResponse)
async def create_task_for_agent(
    agent_id: UUID,
    data: TaskCreate,
    task_service: TaskService = Depends(get_task_service),
):
    """Create and execute a task for the specified agent using Temporal workflows."""
    try:
        # Create and execute task using service layer
        task = await task_service.create_and_execute_task_with_workflow(
            agent_id=agent_id,
            description=data.description,
            parameters=data.parameters,
            user_id=data.user_id,
            enable_agent_communication=data.enable_agent_communication or True,
        )

        # Convert to API response format
        task_response = TaskResponse(
            id=task.id,
            agent_id=task.agent_id,
            description=task.description,
            parameters=task.task_parameters,
            status=task.status,
            result=task.result,
            created_at=task.created_at,
            execution_id=task.execution_id,
        )

        return task_response

    except ValueError as e:
        # Agent validation errors
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        logger.error(f"Failed to create task for agent {agent_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create task: {e!s}") from e


@router.get("/", response_model=list[TaskResponse])
async def list_agent_tasks(
    agent_id: UUID,
    status: str | None = Query(None, description="Filter by task status"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of tasks to return"),
    offset: int = Query(0, ge=0, description="Number of tasks to skip"),
    agent_service: AgentService = Depends(get_agent_service),
    task_service: TaskService = Depends(get_task_service),
):
    """List all tasks for the specified agent."""
    # Verify agent exists
    agent = await agent_service.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    try:
        # Get tasks with workflow status from service
        agent_tasks = await task_service.list_agent_tasks_with_workflow_status(agent_id, limit=limit)

        logger.info(f"Found {len(agent_tasks)} tasks for agent {agent_id} ({agent.name})")

        task_responses: list[TaskResponse] = []

        # Convert service tasks to TaskResponse format
        for task in agent_tasks:
            # Apply status filtering if specified
            if status and task.status.lower() != status.lower():
                continue

            # Create TaskResponse from service task
            task_response = TaskResponse(
                id=task.id,
                agent_id=task.agent_id,
                description=task.description,
                parameters=task.task_parameters or {},
                status=task.status,
                result=task.result,
                created_at=task.created_at,
                execution_id=task.execution_id,
            )
            task_responses.append(task_response)

        # Sort by created_at descending (newest first)
        task_responses.sort(key=lambda x: x.created_at, reverse=True)

        # Apply pagination
        paginated_tasks = task_responses[offset : offset + limit]

        logger.info(f"Returning {len(paginated_tasks)} tasks for agent {agent_id}")

        return paginated_tasks

    except Exception as e:
        logger.error(f"Failed to get tasks for agent {agent_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to retrieve tasks: {e!s}") from e


@router.get("/{task_id}", response_model=TaskResponse)
async def get_agent_task(
    agent_id: UUID,
    task_id: UUID,
    agent_service: AgentService = Depends(get_agent_service),
    workflow_task_service: TemporalWorkflowService = Depends(get_temporal_workflow_service),
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
    workflow_task_service: TemporalWorkflowService = Depends(get_temporal_workflow_service),
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
    workflow_task_service: TemporalWorkflowService = Depends(get_temporal_workflow_service),
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


@router.post("/{task_id}/pause")
async def pause_agent_task(
    agent_id: UUID,
    task_id: UUID,
    agent_service: AgentService = Depends(get_agent_service),
    workflow_task_service: TemporalWorkflowService = Depends(get_temporal_workflow_service),
):
    """Pause a specific task workflow for the specified agent."""
    # Verify agent exists
    agent = await agent_service.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    try:
        # Get current task status to validate it can be paused
        execution_id = f"agent-task-{task_id}"
        status = await workflow_task_service.get_workflow_status(execution_id)

        # Check if task exists
        if status.get("status") == "unknown":
            raise HTTPException(status_code=404, detail="Task not found")

        # Check if task is in a pausable state
        current_status = status.get("status", "").lower()
        if current_status in ["completed", "failed", "cancelled"]:
            raise HTTPException(
                status_code=400, detail=f"Cannot pause task in '{current_status}' state"
            )

        if current_status == "paused":
            raise HTTPException(status_code=400, detail="Task is already paused")

        # Pause the workflow
        success = await workflow_task_service.pause_task(execution_id)

        if success:
            return {
                "status": "paused",
                "task_id": str(task_id),
                "execution_id": execution_id,
                "message": "Task paused successfully",
            }
        else:
            raise HTTPException(status_code=500, detail="Failed to pause task")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to pause task {task_id} for agent {agent_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to pause task: {e!s}") from e


@router.post("/{task_id}/resume")
async def resume_agent_task(
    agent_id: UUID,
    task_id: UUID,
    agent_service: AgentService = Depends(get_agent_service),
    workflow_task_service: TemporalWorkflowService = Depends(get_temporal_workflow_service),
):
    """Resume a paused task workflow for the specified agent."""
    # Verify agent exists
    agent = await agent_service.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    try:
        # Get current task status to validate it can be resumed
        execution_id = f"agent-task-{task_id}"
        status = await workflow_task_service.get_workflow_status(execution_id)

        # Check if task exists
        if status.get("status") == "unknown":
            raise HTTPException(status_code=404, detail="Task not found")

        # Check if task is in a resumable state
        current_status = status.get("status", "").lower()
        if current_status in ["completed", "failed", "cancelled"]:
            raise HTTPException(
                status_code=400, detail=f"Cannot resume task in '{current_status}' state"
            )

        if current_status != "paused":
            raise HTTPException(
                status_code=400,
                detail=f"Cannot resume task that is not paused (current status: {current_status})",
            )

        # Resume the workflow
        success = await workflow_task_service.resume_task(execution_id)

        if success:
            return {
                "status": "running",
                "task_id": str(task_id),
                "execution_id": execution_id,
                "message": "Task resumed successfully",
            }
        else:
            raise HTTPException(status_code=500, detail="Failed to resume task")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to resume task {task_id} for agent {agent_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to resume task: {e!s}") from e


@router.get("/{task_id}/events", response_model=TaskEventResponse)
async def get_task_events(
    agent_id: UUID,
    task_id: UUID,
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=100, description="Number of events per page"),
    event_type: str | None = Query(None, description="Filter by event type"),
    agent_service: AgentService = Depends(get_agent_service),
    workflow_task_service: TemporalWorkflowService = Depends(get_temporal_workflow_service),
):
    """Get paginated task execution events for the specified task."""
    # Verify agent exists
    agent = await agent_service.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    try:
        # Get workflow status to verify task exists
        execution_id = f"agent-task-{task_id}"
        status = await workflow_task_service.get_workflow_status(execution_id)

        # Check if task exists
        if status.get("status") == "unknown":
            raise HTTPException(status_code=404, detail="Task not found")

        # For now, we'll generate mock events based on workflow status
        # In a real implementation, these would be stored during workflow execution
        events = await _get_task_events_from_workflow_history(
            execution_id, str(task_id), str(agent_id), page, page_size, event_type
        )

        # Calculate pagination info
        total_events = len(events)  # This would come from actual event count in real implementation
        has_next = len(events) == page_size  # Simplified logic for demo

        return TaskEventResponse(
            events=events,
            total=total_events,
            page=page,
            page_size=page_size,
            has_next=has_next,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get task events for task {task_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get task events: {e!s}") from e


@router.get("/{task_id}/events/stream")
async def stream_task_events(
    agent_id: UUID,
    task_id: UUID,
    agent_service: AgentService = Depends(get_agent_service),
    workflow_task_service: TemporalWorkflowService = Depends(get_temporal_workflow_service),
):
    """Stream real-time task execution events via Server-Sent Events."""
    # Verify agent exists
    agent = await agent_service.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    try:
        # Get workflow status to verify task exists
        execution_id = f"agent-task-{task_id}"
        status = await workflow_task_service.get_workflow_status(execution_id)

        # Check if task exists
        if status.get("status") == "unknown":
            raise HTTPException(status_code=404, detail="Task not found")

        # Create SSE stream
        async def event_stream() -> AsyncGenerator[str, None]:
            """Generate Server-Sent Events for task updates."""
            try:
                # Send initial connection event
                yield _format_sse_event(
                    "connected",
                    {
                        "task_id": str(task_id),
                        "agent_id": str(agent_id),
                        "execution_id": execution_id,
                        "message": "Connected to task event stream",
                    },
                )

                # In a real implementation, this would listen to actual workflow events
                # For now, we'll simulate periodic status updates
                import asyncio

                last_status = None

                while True:
                    try:
                        # Get current workflow status
                        current_status = await workflow_task_service.get_workflow_status(
                            execution_id
                        )
                        current_status_value = current_status.get("status", "unknown")

                        # Send status update if changed
                        if current_status_value != last_status:
                            yield _format_sse_event(
                                "task_status_changed",
                                {
                                    "task_id": str(task_id),
                                    "agent_id": str(agent_id),
                                    "execution_id": execution_id,
                                    "status": current_status_value,
                                    "timestamp": datetime.now(UTC).isoformat(),
                                    "message": f"Task status changed to {current_status_value}",
                                },
                            )
                            last_status = current_status_value

                        # Break if task is in terminal state
                        if current_status_value in ["completed", "failed", "cancelled"]:
                            yield _format_sse_event(
                                "task_finished",
                                {
                                    "task_id": str(task_id),
                                    "agent_id": str(agent_id),
                                    "execution_id": execution_id,
                                    "status": current_status_value,
                                    "timestamp": datetime.now(UTC).isoformat(),
                                    "message": f"Task finished with status {current_status_value}",
                                },
                            )
                            break

                        # Wait before next check
                        await asyncio.sleep(2)

                    except Exception as e:
                        logger.error(f"Error in SSE stream for task {task_id}: {e}")
                        yield _format_sse_event(
                            "error",
                            {
                                "task_id": str(task_id),
                                "agent_id": str(agent_id),
                                "execution_id": execution_id,
                                "error": str(e),
                                "timestamp": datetime.now(UTC).isoformat(),
                            },
                        )
                        break

            except Exception as e:
                logger.error(f"Fatal error in SSE stream for task {task_id}: {e}")
                yield _format_sse_event(
                    "error",
                    {
                        "task_id": str(task_id),
                        "agent_id": str(agent_id),
                        "execution_id": execution_id,
                        "error": f"Stream error: {e!s}",
                        "timestamp": datetime.now(UTC).isoformat(),
                    },
                )

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "Cache-Control",
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create SSE stream for task {task_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create event stream: {e!s}") from e


async def _get_task_events_from_workflow_history(
    execution_id: str,
    task_id: str,
    agent_id: str,
    page: int,
    page_size: int,
    event_type: str | None = None,
) -> list[TaskEvent]:
    """Get task events from workflow history.

    In a real implementation, this would query Temporal workflow history
    or a dedicated event store. For now, we generate mock events.
    """
    # Mock events for demonstration
    mock_events = [
        TaskEvent(
            id=f"event-{i}",
            task_id=task_id,
            agent_id=agent_id,
            execution_id=execution_id,
            timestamp=datetime.now(UTC),
            event_type="workflow_started" if i == 0 else "activity_completed",
            message=f"Mock event {i} for task {task_id}",
            metadata={"step": i, "mock": True},
        )
        for i in range(1, min(page_size + 1, 6))  # Generate up to 5 mock events
    ]

    # Filter by event type if specified
    if event_type:
        mock_events = [e for e in mock_events if e.event_type == event_type]

    # Apply pagination (simplified for mock data)
    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size

    return mock_events[start_idx:end_idx]


def _format_sse_event(event_type: str, data: dict[str, Any]) -> str:
    """Format data as Server-Sent Event."""
    import json

    event_data = json.dumps(data)
    return f"event: {event_type}\ndata: {event_data}\n\n"
