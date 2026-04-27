import logging
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from agentarea_agents.application.agent_service import AgentService
from agentarea_agents.application.temporal_workflow_service import (
    TemporalWorkflowService,
)
from agentarea_api.api.deps.database import ReadDatabaseSessionDep
from agentarea_api.api.deps.services import (
    get_agent_service,
    get_event_stream_service,
    get_model_instance_service,
    get_read_agent_service,
    get_read_task_service,
    get_task_service,
    get_temporal_workflow_service,
)
from agentarea_common.auth.dependencies import UserContextDep
from sqlalchemy import text
from agentarea_common.events.event_stream_service import EventStreamService
from agentarea_llm.application.model_instance_service import ModelInstanceService
from agentarea_tasks.task_service import TaskService
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class A2UIActionPayload(BaseModel):
    """Validated A2UI action payload from the frontend."""

    name: str = Field(..., max_length=128)
    surface_id: str = Field(..., max_length=64)
    source_component_id: str = Field("", max_length=128)
    context: dict = Field(default_factory=dict)

    model_config = {"extra": "forbid"}


router = APIRouter(prefix="/agents/{agent_id}/tasks", tags=["agent-tasks"])

# Global tasks router (not agent-specific)
global_tasks_router = APIRouter(prefix="/tasks", tags=["tasks"])


class TaskCreate(BaseModel):
    description: str
    parameters: dict[str, Any] = {}
    enable_agent_communication: bool | None = True
    requires_human_approval: bool | None = False
    project_id: str | None = None


class EscalationResolution(BaseModel):
    escalation_id: str
    approved: bool
    comment: str = ""


class TaskCommandPayload(BaseModel):
    command: str
    model_instance_id: str | None = None
    budget_usd: float | None = None
    message: str | None = None
    message_id: str | None = None


class TaskResponse(BaseModel):
    id: UUID
    agent_id: UUID
    description: str
    parameters: dict[str, Any]
    status: str
    result: dict[str, Any] | str | None = None
    created_at: datetime
    execution_id: str | None = None  # Workflow execution ID
    total_cost: float | None = None  # LLM token cost in USD

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
    result: dict[str, Any] | str | None = None
    created_at: datetime
    execution_id: str | None = None
    total_cost: float | None = None  # LLM token cost in USD

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
            total_cost=task.total_cost,
        )


@global_tasks_router.get("/", response_model=list[TaskWithAgent])
async def get_all_tasks(
    user_context: UserContextDep,
    status: str | None = Query(None, description="Filter by task status"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of tasks to return"),
    offset: int = Query(0, ge=0, description="Number of tasks to skip"),
    agent_service: AgentService = Depends(get_read_agent_service),
    task_service: TaskService = Depends(get_read_task_service),
):
    """Get all workspace tasks across all agents.

    Access Control:
        Returns all tasks within the current user's workspace (workspace isolation).
        All users in the same workspace can see all workspace tasks.
    """
    try:
        import asyncio

        # Fetch agents and all workspace tasks in parallel (2 DB queries total)
        agents_result, task_orms = await asyncio.gather(
            agent_service.list(),
            task_service.task_repository.list_all(limit=limit),
        )

        # Build agent lookup map
        agent_map = {str(agent.id): agent.name for agent in agents_result}

        # Convert ORM → domain → TaskWithAgent
        all_tasks: list[TaskWithAgent] = []
        for task_orm in task_orms:
            task = task_service.task_repository._orm_to_domain(task_orm)
            result_dict = task.result if isinstance(task.result, dict) else None
            total_cost = result_dict.get("total_cost") if result_dict else None
            all_tasks.append(
                TaskWithAgent(
                    id=task.id,
                    agent_id=task.agent_id,
                    agent_name=agent_map.get(str(task.agent_id), "Unknown"),
                    description=task.description,
                    parameters=task.parameters,
                    status=task.status,
                    result=task.result,
                    created_at=task.created_at,
                    execution_id=task.execution_id,
                    total_cost=total_cost,
                )
            )

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
        raise HTTPException(status_code=500, detail="Internal server error") from e


@global_tasks_router.get("/{task_id}", response_model=TaskWithAgent)
async def get_task_by_id(
    task_id: UUID,
    user_context: UserContextDep,
    agent_service: AgentService = Depends(get_read_agent_service),
    task_service: TaskService = Depends(get_read_task_service),
):
    """Get a single task by ID across all agents."""
    try:
        task_orm = await task_service.task_repository.get_by_id(task_id)
        if not task_orm:
            raise HTTPException(status_code=404, detail="Task not found")

        task = task_service.task_repository._orm_to_domain(task_orm)
        agent = await agent_service.get(task.agent_id)
        result_dict = task.result if isinstance(task.result, dict) else None
        total_cost = result_dict.get("total_cost") if result_dict else None

        return TaskWithAgent(
            id=task.id,
            agent_id=task.agent_id,
            agent_name=agent.name if agent else "Unknown",
            description=task.description,
            parameters=task.parameters,
            status=task.status,
            result=task.result,
            created_at=task.created_at,
            execution_id=task.execution_id,
            total_cost=total_cost,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get task {task_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error") from e


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
                user_id=user_context.user_id,
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
                async for event in event_stream_service.stream_events_for_task(
                    task.id, event_patterns=["workflow.*"]
                ):
                    # Convert task service event to SSE format
                    event_type = event.get("event_type", "task_event")

                    # Add execution context (use full event_data from stream service)
                    event_data = event.get("event_data", {})
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

        except ValueError:
            # Agent validation errors
            yield _format_sse_event(
                "error",
                {
                    "agent_id": str(agent_id),
                    "error": "Agent validation error",
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
                    "error": "Task creation failed",
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
            user_id=user_context.user_id,
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
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.get("/", response_model=list[TaskResponse])
async def list_agent_tasks(
    agent_id: UUID,
    user_context: UserContextDep,
    status: str | None = Query(None, description="Filter by task status"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of tasks to return"),
    offset: int = Query(0, ge=0, description="Number of tasks to skip"),
    agent_service: AgentService = Depends(get_read_agent_service),
    task_service: TaskService = Depends(get_read_task_service),
):
    """List all tasks for the specified agent.

    Access Control:
        Returns all tasks within the current user's workspace (workspace isolation).
        All users in the same workspace can see all workspace tasks.
    """
    # Verify agent exists
    agent = await agent_service.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    try:
        # Get tasks from DB only (no Temporal enrichment for list view)
        agent_tasks = await task_service.list_agent_tasks(
            agent_id, limit=limit, creator_scoped=False
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
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.get("/{task_id}", response_model=TaskResponse)
async def get_agent_task(
    agent_id: UUID,
    task_id: UUID,
    user_context: UserContextDep,
    agent_service: AgentService = Depends(get_read_agent_service),
    workflow_task_service: TemporalWorkflowService = Depends(get_temporal_workflow_service),
):
    """Get a specific task for the specified agent using workflow status."""
    # Verify agent exists
    agent = await agent_service.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    try:
        # Get workflow status using the execution ID pattern
        execution_id = f"task-{task_id}"
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
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.get("/{task_id}/status")
async def get_agent_task_status(
    agent_id: UUID,
    task_id: UUID,
    user_context: UserContextDep,
    agent_service: AgentService = Depends(get_read_agent_service),
    workflow_task_service: TemporalWorkflowService = Depends(get_temporal_workflow_service),
):
    """Get the execution status of a specific task workflow."""
    # Verify agent exists
    agent = await agent_service.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    try:
        # Get workflow status using the execution ID pattern
        execution_id = f"task-{task_id}"
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
        raise HTTPException(status_code=500, detail="Internal server error") from e


class TaskArtifactItem(BaseModel):
    """A single artifact stored under a task's workspace scope."""

    path: str
    size: int
    content_type: str | None
    last_modified: str | None
    download_url: str


@router.get("/{task_id}/artifacts", response_model=list[TaskArtifactItem])
async def list_task_artifacts(
    agent_id: UUID,
    task_id: UUID,
    user_context: UserContextDep,
    expires_in: int = Query(3600, ge=60, le=86400),
    task_service: TaskService = Depends(get_read_task_service),
) -> list[TaskArtifactItem]:
    """List artifacts the agent produced under ``tasks/{task_id}/``.

    Workspace-scoped: the task must belong to the caller's workspace, or we
    return 404. Each item carries a presigned download URL valid for
    ``expires_in`` seconds (default 1 hour, capped at 24h).
    """
    from agentarea_common.artifacts import ArtifactService

    task = await task_service.get_task(task_id)
    if not task or str(task.agent_id) != str(agent_id):
        raise HTTPException(status_code=404, detail="Task not found")

    svc = ArtifactService()
    prefix = f"tasks/{task_id}/"
    objects = await svc.list(user_context.workspace_id, prefix=prefix)

    items: list[TaskArtifactItem] = []
    for obj in objects:
        url = await svc.presigned_url(user_context.workspace_id, obj.path, expires_in=expires_in)
        items.append(
            TaskArtifactItem(
                path=obj.path,
                size=obj.size,
                content_type=obj.content_type,
                last_modified=obj.last_modified,
                download_url=url,
            )
        )
    return items


class TaskSummary(BaseModel):
    """Headline rollup for a single task, derived from the event log.

    Backed by the ``task_summary`` Postgres view. Stable contract — when
    the view's implementation moves to a materialized view or projection
    table, this shape stays the same. Per-tool breakdowns and per-artifact
    lists are deliberately not here; they live in their own endpoints so
    this stays small and additive.
    """

    task_id: UUID
    agent_id: UUID
    workspace_id: str
    status: str
    started_at: datetime | None = None
    ended_at: datetime | None = None
    duration_ms: float | None = None
    iterations: int = 0
    llm_calls: int = 0
    llm_calls_failed: int = 0
    tools_called: int = 0
    tools_failed: int = 0
    delegations_started: int = 0
    delegations_completed: int = 0
    delegations_failed: int = 0
    cost_usd: float = 0.0
    final_response: str | None = None
    last_error: str | None = None


@router.get("/{task_id}/summary", response_model=TaskSummary)
async def get_task_summary(
    agent_id: UUID,
    task_id: UUID,
    user_context: UserContextDep,
    session: ReadDatabaseSessionDep,
) -> TaskSummary:
    """Per-task rollup derived from the event log via the ``task_summary`` view.

    Workspace-scoped: the row must belong to the caller's workspace and
    the agent must match, or we return 404 (same shape as other task
    endpoints — no information leak).
    """
    row = (
        await session.execute(
            text(
                "SELECT * FROM task_summary "
                "WHERE task_id = :task_id "
                "AND workspace_id = :workspace_id "
                "AND agent_id = :agent_id"
            ),
            {
                "task_id": str(task_id),
                "workspace_id": user_context.workspace_id,
                "agent_id": str(agent_id),
            },
        )
    ).mappings().first()

    if not row:
        raise HTTPException(status_code=404, detail="Task not found")

    return TaskSummary(**dict(row))


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
        execution_id = f"task-{task_id}"
        success = await workflow_task_service.cancel_task(execution_id)

        if success:
            return {"status": "cancelled", "task_id": str(task_id), "execution_id": execution_id}
        else:
            raise HTTPException(status_code=404, detail="Task not found or already completed")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error") from e


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
        execution_id = f"task-{task_id}"
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
        raise HTTPException(status_code=500, detail="Internal server error") from e


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
        execution_id = f"task-{task_id}"
        status = await workflow_task_service.get_workflow_status(execution_id)

        # Check if task exists
        if status.get("status") == "unknown":
            raise HTTPException(status_code=404, detail="Task not found")

        # Reject only terminal states. Signal-based pause does NOT flip
        # Temporal's external status to "paused" (the workflow keeps the
        # "running" execution status while its internal handler waits on
        # the pause flag), so gating on "paused/blocked" here would 400
        # every legitimate resume right after a pause. The resume signal
        # is itself a no-op on workflows that aren't paused, so accepting
        # it from "running" is safe.
        current_status = status.get("status", "").lower()
        if current_status in ["completed", "failed", "cancelled"]:
            raise HTTPException(
                status_code=400, detail=f"Cannot resume task in '{current_status}' state"
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
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.post("/{task_id}/a2ui/action")
async def send_a2ui_action(
    agent_id: UUID,
    task_id: UUID,
    action: A2UIActionPayload,
    user_context: UserContextDep,
    agent_service: AgentService = Depends(get_agent_service),
    workflow_task_service: TemporalWorkflowService = Depends(get_temporal_workflow_service),
):
    """Send an A2UI user action to a running task workflow."""
    agent = await agent_service.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    if not getattr(agent, "a2ui_enabled", False):
        raise HTTPException(status_code=400, detail="Agent does not have A2UI enabled")

    try:
        execution_id = f"agent-task-{task_id}"
        status = await workflow_task_service.get_workflow_status(execution_id)

        if status.get("status") == "unknown":
            raise HTTPException(status_code=404, detail="Task not found")

        current_status = status.get("status", "").lower()
        if current_status in ["completed", "failed", "cancelled"]:
            raise HTTPException(
                status_code=400, detail=f"Cannot send action to task in '{current_status}' state"
            )

        success = await workflow_task_service.send_a2ui_action(execution_id, action.model_dump())

        if success:
            return {
                "status": "accepted",
                "task_id": str(task_id),
                "action_name": action.name,
                "message": "Action sent to workflow",
            }
        else:
            raise HTTPException(status_code=500, detail="Failed to send action to workflow")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to send A2UI action for task {task_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error") from e


async def _resolve_model_info(
    model_instance_id: str,
    model_instance_service: ModelInstanceService,
) -> dict:
    """Resolve model instance from DB and return a ResolvedModelInfo-compatible dict.

    The api_key_secret field is the secret manager key name stored in
    provider_config.api_key (NOT the actual decrypted key).
    """
    instance = await model_instance_service.get(UUID(model_instance_id))
    if not instance:
        raise HTTPException(status_code=404, detail="Model instance not found")

    provider_config = instance.provider_config
    model_spec = instance.model_spec
    provider_spec = provider_config.provider_spec if provider_config else None

    return {
        "model_id": str(instance.id),
        "provider_type": provider_spec.provider_type if provider_spec else "",
        "model_name": model_spec.model_name if model_spec else "",
        "api_key_secret": provider_config.api_key if provider_config else None,
        "endpoint_url": provider_config.endpoint_url if provider_config else None,
        "context_window": model_spec.context_window if model_spec else 128000,
        "display_name": model_spec.display_name if model_spec else None,
        "provider_display_name": provider_spec.name if provider_spec else None,
        "resolved_at": datetime.now(UTC).isoformat(),
    }


@router.post("/{task_id}/command")
async def send_task_command(
    agent_id: UUID,
    task_id: UUID,
    payload: TaskCommandPayload,
    user_context: UserContextDep,
    agent_service: AgentService = Depends(get_agent_service),
    workflow_task_service: TemporalWorkflowService = Depends(get_temporal_workflow_service),
    model_instance_service: ModelInstanceService = Depends(get_model_instance_service),
):
    """Send a command to a running task workflow."""
    # Verify agent exists
    agent = await agent_service.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    execution_id = f"task-{task_id}"

    try:
        if payload.command == "change_model":
            if not payload.model_instance_id:
                raise HTTPException(
                    status_code=400, detail="model_instance_id is required for change_model"
                )
            resolved = await _resolve_model_info(payload.model_instance_id, model_instance_service)
            await workflow_task_service.send_workflow_command(
                execution_id, "change_model", resolved
            )

        elif payload.command == "queue_message":
            if not payload.message:
                raise HTTPException(status_code=400, detail="message is required for queue_message")
            await workflow_task_service.send_workflow_command(
                execution_id, "queue_message", {"message": payload.message}
            )

        elif payload.command == "remove_message":
            if not payload.message_id:
                raise HTTPException(
                    status_code=400, detail="message_id is required for remove_message"
                )
            await workflow_task_service.send_workflow_command(
                execution_id, "remove_message", {"message_id": payload.message_id}
            )

        elif payload.command == "update_budget":
            await workflow_task_service.send_workflow_command(
                execution_id, "update_budget", {"budget_usd": payload.budget_usd}
            )

        else:
            raise HTTPException(status_code=400, detail=f"Unknown command: {payload.command}")

        return {"status": "accepted", "command": payload.command}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Failed to send command '{payload.command}' for task {task_id}: {e}", exc_info=True
        )
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.post("/{task_id}/resolve-escalation")
async def resolve_task_escalation(
    agent_id: UUID,
    task_id: UUID,
    data: EscalationResolution,
    user_context: UserContextDep,
    agent_service: AgentService = Depends(get_agent_service),
    workflow_task_service: TemporalWorkflowService = Depends(get_temporal_workflow_service),
):
    """Resolve a tool escalation for the specified task workflow."""
    # Verify agent exists
    agent = await agent_service.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    try:
        execution_id = f"task-{task_id}"
        success = await workflow_task_service.resolve_escalation(
            execution_id, data.escalation_id, data.approved, data.comment
        )

        if success:
            return {
                "status": "resolved",
                "escalation_id": data.escalation_id,
                "approved": data.approved,
            }
        else:
            raise HTTPException(status_code=500, detail="Failed to resolve escalation")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to resolve escalation for task {task_id}, agent {agent_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.get("/{task_id}/events", response_model=TaskEventResponse)
async def get_task_events(
    agent_id: UUID,
    task_id: UUID,
    user_context: UserContextDep,
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=100, description="Number of events per page"),
    event_type: str | None = Query(None, description="Filter by event type"),
    agent_service: AgentService = Depends(get_read_agent_service),
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
                    execution_id=row.data.get("execution_id")
                    or row.event_metadata.get("execution_id", "unknown"),
                    timestamp=row.timestamp,
                    event_type=row.event_type,
                    message=row.data.get("message", f"Event: {row.event_type}"),
                    metadata=dict(row.data) if row.data else {},
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
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.get("/{task_id}/events/stream")
async def stream_task_events(
    agent_id: UUID,
    task_id: UUID,
    user_context: UserContextDep,
    agent_service: AgentService = Depends(get_read_agent_service),
    task_service: TaskService = Depends(get_read_task_service),
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
                async for event in event_stream_service.stream_events_for_task(
                    task_id, event_patterns=["workflow.*"]
                ):
                    # Use protocol event structure directly - task service already
                    # formats it properly
                    event_type = event.get("event_type", "task_event")
                    event_data_dict = event.get("event_data", {})

                    # Create protocol-compliant SSE event with filtered data
                    # Note: event_stream_service returns "event_data" containing the full event data
                    sse_event = {
                        "event_type": event_type,
                        "event_id": event_data_dict.get("event_id"),
                        "timestamp": event_data_dict.get("timestamp"),
                        "data": _filter_domain_fields(event_data_dict),
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
                        "error": "Stream error",
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
        raise HTTPException(status_code=500, detail="Internal server error") from e


# Mock function removed - now using real database queries


def _filter_domain_fields(data: dict[str, Any]) -> dict[str, Any]:
    """Remove domain-specific fields from protocol event data for internal streams.

    For tool and LLM events, extracts original_data fields and merges them with the response
    to ensure proper UI display of event content.
    """
    if not isinstance(data, dict):
        return data

    # Handle nested payloads where event structure is wrapped under "data"
    # Example shape:
    # {
    #   "event_id": "...",
    #   "timestamp": "...",
    #   "event_type": "workflow.LLMCallChunk",
    #   "data": {
    #       "aggregate_id": "...",
    #       "original_event_type": "LLMCallChunk",
    #       "original_data": {"task_id": "...", "chunk": "...", ...}
    #   }
    # }
    if "data" in data and isinstance(data["data"], dict):
        outer_context = {k: v for k, v in data.items() if k != "data"}
        inner_data = data["data"]

        # Recursively filter inner structure first
        processed_inner = _filter_domain_fields(inner_data)

        # Merge inner (UI-relevant) fields with outer context fields we injected
        # upstream. Inner fields should take precedence for content fields;
        # outer provides task/agent/execution ids
        merged: dict[str, Any] = {**outer_context, **processed_inner}
        return merged

    # For tool events and LLM events, extract original_data content for UI display
    if "original_event_type" in data:
        original_event_type = data.get("original_event_type", "")
        if (
            original_event_type.startswith("ToolCall")
            or original_event_type.startswith("LLMCall")
            or original_event_type.startswith("A2UI")
            or "tool_name" in str(data.get("original_data", {}))
        ):
            # Extract original_data and merge it with filtered domain fields
            original_data = data.get("original_data", {})
            if isinstance(original_data, dict):
                # Start with domain fields (excluding internal ones)
                result = {
                    k: v
                    for k, v in data.items()
                    if k
                    not in (
                        "original_event_type",
                        "original_data",
                        "aggregate_id",
                        "aggregate_type",
                    )
                }
                # Merge in original_data fields (UI-relevant content)
                result.update(original_data)
                return result
            # Fallback: keep original_data as nested field
            return {k: v for k, v in data.items() if k != "original_event_type"}

    # For other events, filter out both original_event_type and original_data
    return {k: v for k, v in data.items() if k not in ("original_event_type", "original_data")}


def _format_sse_event(event_type: str, data: dict[str, Any]) -> str:
    """Format data as Server-Sent Event."""
    import json

    event_data = json.dumps(data)
    return f"event: {event_type}\ndata: {event_data}\n\n"
