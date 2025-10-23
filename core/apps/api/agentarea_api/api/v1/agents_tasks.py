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
    get_event_stream_service,
    get_task_service,
    get_temporal_workflow_service,
)
from agentarea_common.auth.dependencies import UserContextDep
from agentarea_common.events.event_stream_service import EventStreamService
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
    requires_human_approval: bool | None = False


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
    user_context: UserContextDep,
    status: str | None = Query(None, description="Filter by task status"),
    created_by: str | None = Query(
        None, description="Filter by creator: 'me' for current user's tasks only"
    ),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of tasks to return"),
    offset: int = Query(0, ge=0, description="Number of tasks to skip"),
    agent_service: AgentService = Depends(get_agent_service),
    task_service: TaskService = Depends(get_task_service),
):
    """Get all workspace tasks across all agents with optional filtering."""
    try:
        # Determine if we should filter by creator
        creator_scoped = created_by == "me"

        # Get all workspace agents (or user's agents if creator_scoped)
        agents = await agent_service.list(creator_scoped=creator_scoped)

        all_tasks: list[TaskWithAgent] = []

        # For each agent, get their tasks from service
        for agent in agents:
            try:
                # Get tasks with workflow status from service
                # Note: task filtering by creator is handled at the agent level
                agent_tasks = await task_service.list_agent_tasks_with_workflow_status(
                    agent.id, limit=limit, creator_scoped=creator_scoped
                )

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


@router.post("/")
async def create_task_for_agent_with_stream(
    agent_id: UUID,
    data: TaskCreate,
    user_context: UserContextDep,
    task_service: TaskService = Depends(get_task_service),
    agent_service: AgentService = Depends(get_agent_service),
    event_stream_service: EventStreamService = Depends(get_event_stream_service),
):
    """Create and execute a task for the specified agent with real-time SSE stream."""
    # Verify agent exists
    agent = await agent_service.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    async def task_creation_stream() -> AsyncGenerator[str, None]:
        """Generate Server-Sent Events for task creation and execution."""
        task = None
        try:
            # Send initial connection event
            yield _format_sse_event(
                "connected",
                {
                    "agent_id": str(agent_id),
                    "agent_name": agent.name,
                    "message": "Starting task creation",
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )

            # Create and execute task using service layer
            task = await task_service.create_and_execute_task_with_workflow(
                agent_id=agent_id,
                description=data.description,
                workspace_id=user_context.workspace_id,
                parameters=data.parameters,
                user_id=data.user_id,
                enable_agent_communication=data.enable_agent_communication or True,
                requires_human_approval=data.requires_human_approval or False,
            )

            # Send task created event
            yield _format_sse_event(
                "task_created",
                {
                    "task_id": str(task.id),
                    "agent_id": str(agent_id),
                    "description": task.description,
                    "status": task.status,
                    "execution_id": task.execution_id,
                    "created_at": task.created_at.isoformat(),
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )

            # If workflow started successfully, stream events from event stream service
            if task.execution_id and task.status in ["running", "pending"]:
                async for event in event_stream_service.stream_events_for_task(task.id, event_patterns=["workflow.*"]):
                    # Convert task service event to SSE format
                    event_type = event.get("event_type", "task_event")

                    # Add execution context
                    event_data = event.get("data", {})
                    event_data.update(
                        {
                            "task_id": str(task.id),
                            "agent_id": str(agent_id),
                            "execution_id": task.execution_id,
                            "timestamp": event.get("timestamp", datetime.now(UTC).isoformat()),
                        }
                    )

                    # Filter out domain-specific fields for internal stream consumers
                    filtered_event_data = _filter_domain_fields(event_data)

                    yield _format_sse_event(event_type, filtered_event_data)

                    # Check for terminal states
                    if event_type in [
                        "task_completed",
                        "task_failed",
                        "task_cancelled",
                        "workflow_completed",
                        "workflow_failed",
                    ]:
                        logger.info(f"Task {task.id} reached terminal state: {event_type}")
                        break
            else:
                # Task failed to start
                yield _format_sse_event(
                    "task_failed",
                    {
                        "task_id": str(task.id),
                        "agent_id": str(agent_id),
                        "error": "Task failed to start workflow",
                        "status": task.status,
                        "result": task.result,
                        "timestamp": datetime.now(UTC).isoformat(),
                    },
                )

        except ValueError as e:
            # Agent validation errors
            yield _format_sse_event(
                "error",
                {
                    "agent_id": str(agent_id),
                    "error": f"Agent validation error: {e!s}",
                    "error_type": "agent_not_found",
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )
        except Exception as e:
            logger.error(f"Failed to create task for agent {agent_id}: {e}")
            yield _format_sse_event(
                "error",
                {
                    "task_id": str(task.id) if task else None,
                    "agent_id": str(agent_id),
                    "error": f"Task creation failed: {e!s}",
                    "error_type": "creation_failed",
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )

    return StreamingResponse(
        task_creation_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Cache-Control",
        },
    )


@router.post("/sync", response_model=TaskResponse)
async def create_task_for_agent_sync(
    agent_id: UUID,
    data: TaskCreate,
    user_context: UserContextDep,
    task_service: TaskService = Depends(get_task_service),
):
    """Create and execute a task for the specified agent (synchronous response)."""
    try:
        # Create and execute task using service layer
        task = await task_service.create_and_execute_task_with_workflow(
            agent_id=agent_id,
            description=data.description,
            workspace_id=user_context.workspace_id,
            parameters=data.parameters,
            user_id=data.user_id,
            enable_agent_communication=data.enable_agent_communication or True,
            requires_human_approval=data.requires_human_approval or False,
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
    user_context: UserContextDep,
    status: str | None = Query(None, description="Filter by task status"),
    created_by: str | None = Query(
        None, description="Filter by creator: 'me' for current user's tasks only"
    ),
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
        # Determine if we should filter by creator
        creator_scoped = created_by == "me"

        # Get tasks with workflow status from service
        agent_tasks = await task_service.list_agent_tasks_with_workflow_status(
            agent_id, limit=limit, creator_scoped=creator_scoped
        )

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
    user_context: UserContextDep,
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
    user_context: UserContextDep,
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
    user_context: UserContextDep,
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
    user_context: UserContextDep,
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
    user_context: UserContextDep,
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
    user_context: UserContextDep,
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=100, description="Number of events per page"),
    event_type: str | None = Query(None, description="Filter by event type"),
    agent_service: AgentService = Depends(get_agent_service),
):
    """Get paginated task execution events for the specified task from database."""
    # Verify agent exists
    agent = await agent_service.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    try:
        from agentarea_api.api.deps.database import get_db_session
        from sqlalchemy import text

        # Get database session
        async with get_db_session() as session:
            # Build the query with optional event type filter
            base_query = """
                SELECT id, task_id, event_type, timestamp, data, event_metadata,
                       COUNT(*) OVER() as total_count
                FROM task_events
                WHERE task_id = :task_id
            """

            params = {"task_id": str(task_id)}

            if event_type:
                base_query += " AND event_type = :event_type"
                params["event_type"] = event_type

            base_query += """
                ORDER BY timestamp ASC
                LIMIT :limit OFFSET :offset
            """

            params.update({"limit": page_size, "offset": (page - 1) * page_size})

            # Execute query
            result = await session.execute(text(base_query), params)
            rows = result.fetchall()

        if not rows:
            # No events found - return empty response
            return TaskEventResponse(
                events=[],
                total=0,
                page=page,
                page_size=page_size,
                has_next=False,
            )

        # Convert database rows to TaskEvent objects
        total_events = rows[0].total_count if rows else 0
        events = []

        for row in rows:
            events.append(
                TaskEvent(
                    id=str(row.id),
                    task_id=str(row.task_id),
                    agent_id=str(agent_id),
                    execution_id=row.event_metadata.get("execution_id", "unknown"),
                    timestamp=row.timestamp,
                    event_type=row.event_type,
                    message=row.data.get("message", f"Event: {row.event_type}"),
                    metadata=dict(row.event_metadata) if row.event_metadata else {},
                )
            )

        # Calculate pagination info
        has_next = (page * page_size) < total_events

        return TaskEventResponse(
            events=events,
            total=total_events,
            page=page,
            page_size=page_size,
            has_next=has_next,
        )

    except Exception as e:
        logger.error(f"Failed to get task events for task {task_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get task events: {e!s}") from e


@router.get("/{task_id}/events/stream")
async def stream_task_events(
    agent_id: UUID,
    task_id: UUID,
    user_context: UserContextDep,
    agent_service: AgentService = Depends(get_agent_service),
    task_service: TaskService = Depends(get_task_service),
    event_stream_service: EventStreamService = Depends(get_event_stream_service),
):
    """Stream real-time task execution events via Server-Sent Events."""
    # Verify agent exists
    agent = await agent_service.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    try:
        # Verify task exists
        task = await task_service.get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")

        # Create SSE stream using the task service's event streaming
        async def event_stream() -> AsyncGenerator[str, None]:
            """Generate Server-Sent Events for task updates."""
            try:
                # Send initial connection event
                yield _format_sse_event(
                    "connected",
                    {
                        "task_id": str(task_id),
                        "agent_id": str(agent_id),
                        "execution_id": task.execution_id,
                        "message": "Connected to task event stream",
                        "timestamp": datetime.now(UTC).isoformat(),
                    },
                )

                # Stream events from event stream service
                async for event in event_stream_service.stream_events_for_task(task_id, event_patterns=["workflow.*"]):
                    # Use protocol event structure directly - task service already formats it properly
                    event_type = event.get("event_type", "task_event")

                    # Create protocol-compliant SSE event with filtered data
                    sse_event = {
                        "event_type": event_type,
                        "event_id": event.get("event_id"),
                        "timestamp": event.get("timestamp"),
                        "data": _filter_domain_fields(event.get("data", {})),
                    }

                    yield _format_sse_event(event_type, sse_event)

                    # Check for terminal states
                    if event_type in [
                        "task_completed",
                        "task_failed",
                        "task_cancelled",
                        "workflow_completed",
                        "workflow_failed",
                    ]:
                        logger.info(f"Task {task_id} reached terminal state: {event_type}")
                        break

            except Exception as e:
                logger.error(f"Fatal error in SSE stream for task {task_id}: {e}")
                yield _format_sse_event(
                    "error",
                    {
                        "task_id": str(task_id),
                        "agent_id": str(agent_id),
                        "execution_id": task.execution_id,
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


# Mock function removed - now using real database queries


def _filter_domain_fields(data: dict[str, Any]) -> dict[str, Any]:
    """Remove domain-specific fields from protocol event data for internal streams.

    Preserves original_data for tool events and LLM events that need it for proper UI display.
    """
    if not isinstance(data, dict):
        return data

    # For tool events and LLM events, preserve original_data as it contains essential display information
    if "original_event_type" in data:
        original_event_type = data.get("original_event_type", "")
        if (
            original_event_type.startswith("ToolCall")
            or original_event_type.startswith("LLMCall")
            or "tool_name" in str(data.get("original_data", {}))
        ):
            # Keep original_data for tool and LLM events
            return {k: v for k, v in data.items() if k != "original_event_type"}

    # For other events, filter out both original_event_type and original_data
    return {k: v for k, v in data.items() if k not in ("original_event_type", "original_data")}


def _format_sse_event(event_type: str, data: dict[str, Any]) -> str:
    """Format data as Server-Sent Event."""
    import json

    event_data = json.dumps(data)
    return f"event: {event_type}\ndata: {event_data}\n\n"
