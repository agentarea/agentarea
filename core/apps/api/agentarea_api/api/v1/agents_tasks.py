import logging
from datetime import UTC, datetime
from typing import Any, AsyncGenerator
from uuid import UUID, uuid4

from agentarea_agents.application.agent_service import AgentService
from agentarea_agents.application.temporal_workflow_service import (
    TemporalWorkflowService,
)
from agentarea_api.api.deps.events import EventBrokerDep
from agentarea_api.api.deps.services import get_agent_service, get_temporal_workflow_service
from agentarea_tasks.application.service import TaskService
from agentarea_tasks.infrastructure.repository import TaskRepository
from agentarea_tasks.domain.events import TaskCreated
from agentarea_common.config import get_database
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
    workflow_task_service: TemporalWorkflowService = Depends(get_temporal_workflow_service),
):
    """Get all tasks across all agents with optional filtering."""
    try:
        # Get all agents first to create a lookup map
        agents = await agent_service.list()
        agent_lookup = {str(agent.id): agent.name for agent in agents}
        
        all_tasks: list[TaskWithAgent] = []
        
        # Query tasks from database
        database = get_database()
        async with database.async_session_factory() as session:
            task_repository = TaskRepository(session)
            
            # For each agent, get their tasks from database
            for agent in agents:
                try:
                    # Get tasks for this agent from database
                    agent_tasks = await task_repository.list_by_agent(agent.id, limit=limit)
                    
                    logger.info(f"Found {len(agent_tasks)} tasks for agent {agent.id} ({agent.name})")
                    
                    # Convert database tasks to TaskWithAgent format
                    for db_task in agent_tasks:
                        # Get current workflow status if execution_id exists
                        current_status = db_task.status
                        if db_task.execution_id:
                            try:
                                workflow_status = await workflow_task_service.get_workflow_status(db_task.execution_id)
                                if workflow_status.get("status") != "unknown":
                                    current_status = workflow_status.get("status", db_task.status)
                            except Exception as e:
                                logger.debug(f"Could not get workflow status for task {db_task.id}: {e}")
                        
                        # Create TaskWithAgent from database task
                        task_with_agent = TaskWithAgent(
                            id=db_task.id,
                            agent_id=db_task.agent_id,
                            agent_name=agent.name,
                            description=db_task.description,
                            parameters=db_task.parameters,
                            status=current_status,
                            result=db_task.result,
                            created_at=db_task.created_at,
                            execution_id=db_task.execution_id,
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
        paginated_tasks = all_tasks[offset:offset + limit]
        
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


# Dependency injection for task service
async def get_task_service(event_broker: EventBrokerDep) -> TaskService:
    """Get task service with database session and event broker."""
    database = get_database()
    async with database.async_session_factory() as session:
        repository = TaskRepository(session)
        return TaskService(repository, event_broker)


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

    # Store task in database first
    database = get_database()
    async with database.async_session_factory() as session:
        task_repository = TaskRepository(session)
        
        # Create task in database
        from agentarea_tasks.domain.models import TaskCreate as DomainTaskCreate
        task_create = DomainTaskCreate(
            agent_id=agent_id,
            description=data.description,
            parameters=data.parameters,
            user_id=data.user_id or "api_user",
            metadata={
                "created_via": "api",
                "agent_name": agent.name,
                "enable_agent_communication": data.enable_agent_communication,
                "status": "created",
                "task_id": task_id_str,  # Store the task ID in metadata
            }
        )
        
        # Store in database
        stored_task = await task_repository.create(task_create)
        
        logger.info(f"Task {task_id_str} stored in database for agent {agent_id} (DB ID: {stored_task.id})")

    # Create the task response immediately - this ensures the task exists even if workflow fails
    # Status starts as "pending" to indicate workflow hasn't started yet
    task_response = TaskResponse.create_new(
        task_id=task_id,
        agent_id=agent_id,
        description=data.description,
        parameters=data.parameters,
        execution_id=None,  # Will be updated after workflow starts
    )
    # Override status to "pending" initially
    task_response.status = "pending"

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
            "status": "created",  # Initial status
        },
    )

    # Publish the event to the event broker
    await event_broker.publish(task_created_event)

    logger.info(f"Task {task_id_str} created for agent {agent_id}")

    # Now try to execute the workflow - if this fails, the task still exists
    try:
        # Execute task using Temporal workflow - this returns immediately!
        result = await workflow_task_service.execute_agent_task_async(
            agent_id=agent_id,
            task_query=data.description,
            user_id=data.user_id or "api_user",
            task_parameters=data.parameters,
        )
        execution_id = result.get("execution_id")

        # Update the task response with execution ID
        task_response.execution_id = execution_id
        task_response.status = "running"  # Update status to running

        logger.info(
            f"Task {task_id_str} started with workflow execution ID "
            f"{execution_id} for agent {agent_id}"
        )

        # Publish workflow started event
        workflow_started_event = TaskCreated(
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
                "status": "running",
                "workflow_started": True,
            },
        )
        await event_broker.publish(workflow_started_event)

    except Exception as e:
        logger.error(f"Failed to start task workflow for agent {agent_id}: {e}")
        
        # Update task status to failed, but still return the task
        task_response.status = "failed"
        task_response.result = {"error": str(e), "error_type": "workflow_start_failed"}
        
        # Publish workflow failed event
        workflow_failed_event = TaskCreated(
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
                "status": "failed",
                "error": str(e),
                "workflow_failed": True,
            },
        )
        await event_broker.publish(workflow_failed_event)
        
        logger.info(f"Task {task_id_str} created but workflow failed to start: {e}")

    return task_response


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

    # TODO: Implement proper task storage and retrieval
    # For now, we return an empty list since tasks are managed via Temporal workflows
    # In a production system, you would:
    # 1. Store task metadata in a database when created
    # 2. Query that database here to return all tasks for the agent
    # 3. Enrich with current workflow status from Temporal
    
    logger.info(
        f"Task listing requested for agent {agent_id}. "
        f"Individual task status available via /{{task_id}}/status endpoint."
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


@router.post("/{task_id}/pause")
async def pause_agent_task(
    agent_id: UUID,
    task_id: UUID,
    agent_service: AgentService = Depends(get_agent_service),
    workflow_task_service: TemporalWorkflowService = Depends(
        get_temporal_workflow_service
    ),
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
                status_code=400, 
                detail=f"Cannot pause task in '{current_status}' state"
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
                "message": "Task paused successfully"
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
    workflow_task_service: TemporalWorkflowService = Depends(
        get_temporal_workflow_service
    ),
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
                status_code=400, 
                detail=f"Cannot resume task in '{current_status}' state"
            )
        
        if current_status != "paused":
            raise HTTPException(
                status_code=400, 
                detail=f"Cannot resume task that is not paused (current status: {current_status})"
            )

        # Resume the workflow
        success = await workflow_task_service.resume_task(execution_id)

        if success:
            return {
                "status": "running", 
                "task_id": str(task_id), 
                "execution_id": execution_id,
                "message": "Task resumed successfully"
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
    workflow_task_service: TemporalWorkflowService = Depends(
        get_temporal_workflow_service
    ),
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
    workflow_task_service: TemporalWorkflowService = Depends(
        get_temporal_workflow_service
    ),
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
                yield _format_sse_event("connected", {
                    "task_id": str(task_id),
                    "agent_id": str(agent_id),
                    "execution_id": execution_id,
                    "message": "Connected to task event stream"
                })
                
                # In a real implementation, this would listen to actual workflow events
                # For now, we'll simulate periodic status updates
                import asyncio
                last_status = None
                
                while True:
                    try:
                        # Get current workflow status
                        current_status = await workflow_task_service.get_workflow_status(execution_id)
                        current_status_value = current_status.get("status", "unknown")
                        
                        # Send status update if changed
                        if current_status_value != last_status:
                            yield _format_sse_event("task_status_changed", {
                                "task_id": str(task_id),
                                "agent_id": str(agent_id),
                                "execution_id": execution_id,
                                "status": current_status_value,
                                "timestamp": datetime.now(UTC).isoformat(),
                                "message": f"Task status changed to {current_status_value}"
                            })
                            last_status = current_status_value
                        
                        # Break if task is in terminal state
                        if current_status_value in ["completed", "failed", "cancelled"]:
                            yield _format_sse_event("task_finished", {
                                "task_id": str(task_id),
                                "agent_id": str(agent_id),
                                "execution_id": execution_id,
                                "status": current_status_value,
                                "timestamp": datetime.now(UTC).isoformat(),
                                "message": f"Task finished with status {current_status_value}"
                            })
                            break
                        
                        # Wait before next check
                        await asyncio.sleep(2)
                        
                    except Exception as e:
                        logger.error(f"Error in SSE stream for task {task_id}: {e}")
                        yield _format_sse_event("error", {
                            "task_id": str(task_id),
                            "agent_id": str(agent_id),
                            "execution_id": execution_id,
                            "error": str(e),
                            "timestamp": datetime.now(UTC).isoformat()
                        })
                        break
                        
            except Exception as e:
                logger.error(f"Fatal error in SSE stream for task {task_id}: {e}")
                yield _format_sse_event("error", {
                    "task_id": str(task_id),
                    "agent_id": str(agent_id),
                    "execution_id": execution_id,
                    "error": f"Stream error: {str(e)}",
                    "timestamp": datetime.now(UTC).isoformat()
                })

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
    """
    Get task events from workflow history.
    
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
            metadata={"step": i, "mock": True}
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
