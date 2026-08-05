import logging
import mimetypes
import re
import unicodedata
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import quote
from uuid import UUID, uuid4

import httpx
from agentarea_agents.application.agent_service import AgentService
from agentarea_agents.application.temporal_workflow_service import (
    TemporalWorkflowService,
)
from agentarea_api.api.deps.database import ReadDatabaseSessionDep
from agentarea_api.api.deps.services import (
    BaseSecretManagerDep,
    get_agent_service,
    get_model_instance_service,
    get_read_agent_service,
    get_read_task_service,
    get_task_service,
    get_temporal_workflow_service,
)
from agentarea_common.auth.dependencies import UserContextDep
from agentarea_common.base import ReadRepositoryFactoryDep
from agentarea_common.config import get_settings
from agentarea_common.events.contract import TASK_CANCELLED, TASK_COMPLETED, TASK_FAILED
from agentarea_common.money import ZERO, Money, serialize_money
from agentarea_common.utils.types import UtcDatetime
from agentarea_governance.domain.policies import PolicyDocument, PolicyValidationError
from agentarea_llm.application.model_instance_service import ModelInstanceService
from agentarea_tasks.domain.exceptions import AgentModelNotConfiguredError
from agentarea_tasks.infrastructure.repository import TaskEventRepository
from agentarea_tasks.schemas.dto import RunCreate, RunExecutionConfig
from agentarea_tasks.task_service import TaskService
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import text

logger = logging.getLogger(__name__)


class A2UIActionPayload(BaseModel):
    """Validated A2UI action payload from the frontend."""

    name: str = Field(..., max_length=128)
    surface_id: str = Field(..., max_length=64)
    source_component_id: str = Field("", max_length=128)
    context: dict = Field(default_factory=dict)

    model_config = {"extra": "forbid"}


class InputSecretValue(BaseModel):
    """Secret value submitted through the protected input endpoint."""

    value: str = Field(..., min_length=1)
    secret_name: str | None = Field(default=None, max_length=256)

    model_config = {"extra": "forbid"}


class TaskInputSubmission(BaseModel):
    """Structured user input submission for a pending workflow input request."""

    input_request_id: str = Field(..., min_length=1, max_length=128)
    answers: dict[str, Any] = Field(default_factory=dict)
    secrets: dict[str, str | InputSecretValue] = Field(default_factory=dict)

    model_config = {"extra": "forbid"}


router = APIRouter(prefix="/agents/{agent_id}/tasks", tags=["agent-tasks"])

# Global tasks router (not agent-specific)
global_tasks_router = APIRouter(prefix="/tasks", tags=["tasks"])


class TaskCreate(BaseModel):
    description: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    execution: RunExecutionConfig | None = None
    requires_human_approval: bool | None = False
    project_id: str | None = None
    task_policy: PolicyDocument | None = None
    # staging refs from POST /v1/files (purpose=attachment) or POST /v1/files/upload-url
    attachments: list[str] | None = None


def _attachment_content_disposition(filename: str) -> str:
    """Return an ASCII fallback plus an RFC 5987 UTF-8 filename."""
    fallback = unicodedata.normalize("NFKD", filename).encode("ascii", "ignore").decode()
    fallback = re.sub(r"[^A-Za-z0-9._-]+", "_", fallback).strip("._-") or "artifact.bin"
    encoded = quote(filename, safe="")
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{encoded}"


def _dedupe_attachment_name(name: str, used: set[str]) -> str:
    """Return a name unique within ``used`` by inserting ``-N`` before the extension.

    Two attachments can carry the same basename (distinct staging refs, identical
    filenames); collapsing them into one manifest entry would silently drop a
    file, so disambiguate deterministically: ``report.csv`` -> ``report-1.csv``.
    """
    if name not in used:
        return name
    suffix = PurePosixPath(name).suffix
    base = name[: len(name) - len(suffix)] if suffix else name
    index = 1
    while True:
        candidate = f"{base}-{index}{suffix}"
        if candidate not in used:
            return candidate
        index += 1


async def _stage_attachments_into_task(
    workspace_id: str,
    reserved_task_id: UUID,
    refs: list[str],
    user_id: str,
) -> list[dict[str, Any]]:
    """Resolve staging refs into a reserved task's ``inputs/attachments`` scope.

    Each ref (``staging/{id}/{filename}`` from ``POST /v1/files`` with
    ``purpose=attachment`` or a presigned ``POST /v1/files/upload-url``) is HEADed
    to resolve its verified sha256, size and content type, then copied
    server-side into the task's content-addressed store via ``attach_object``.
    The bytes never transit this process. Returns the attachment descriptors
    persisted alongside the run. Raises HTTP errors mirroring the
    workspace-commit failure modes. Staging objects are left in place; the
    caller deletes them only after a successful dispatch.
    """
    from agentarea_common.artifacts import (
        ArtifactActor,
        ArtifactService,
        DbArtifactEventRecorder,
        WorkspaceConflictError,
        WorkspaceQuotaError,
        WorkspaceRepository,
        WorkspaceValidationError,
    )

    artifact_service = ArtifactService()
    workspace_repository = WorkspaceRepository(
        recorder=DbArtifactEventRecorder(),
        actor=ArtifactActor(user_id=user_id),
    )

    descriptors: list[dict[str, Any]] = []
    used_names: set[str] = set()
    for ref in refs:
        if not ref.startswith("staging/"):
            raise HTTPException(status_code=422, detail=f"Invalid attachment ref: {ref}")
        head = await artifact_service.head(workspace_id, ref)
        if head is None:
            raise HTTPException(status_code=404, detail="attachment ref not found")
        sha256 = head.get("sha256")
        if not sha256:
            raise HTTPException(
                status_code=422, detail="attachment integrity digest is unavailable"
            )
        size = int(head.get("size") or 0)
        content_type = head.get("content_type") or "application/octet-stream"
        name = _dedupe_attachment_name(ref.rsplit("/", 1)[-1] or "attachment", used_names)
        used_names.add(name)
        rel = f"inputs/attachments/{name}"
        try:
            await workspace_repository.attach_object(
                workspace_id,
                str(reserved_task_id),
                rel,
                source_key=ref,
                expected_sha256=sha256,
                expected_size=size,
                content_type=content_type,
                owner=f"task-attachment-upload-{reserved_task_id}",
            )
        except WorkspaceQuotaError as exc:
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        except WorkspaceConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except WorkspaceValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            logger.error(
                "Failed to attach staged object for task %s", reserved_task_id, exc_info=True
            )
            raise HTTPException(status_code=500, detail="Attachment storage failed") from exc
        descriptors.append(
            {
                "relative_path": rel,
                "filename": name,
                "size": size,
                "content_type": content_type,
                "sha256": sha256,
            }
        )

    return descriptors


async def _delete_staging_refs(workspace_id: str, refs: list[str], user_id: str) -> None:
    """Best-effort delete of consumed staging objects after a successful dispatch.

    Deleting only after dispatch means a failed dispatch leaves the upload intact
    for a retry instead of consuming it. Never raises: an orphaned staging object
    is reclaimed by lifecycle cleanup, not worth failing a launched task over.
    """
    from agentarea_common.artifacts import (
        ArtifactActor,
        ArtifactService,
        DbArtifactEventRecorder,
    )

    artifact_service = ArtifactService(
        recorder=DbArtifactEventRecorder(),
        actor=ArtifactActor(user_id=user_id),
    )
    for ref in refs:
        try:
            await artifact_service.delete(workspace_id, ref)
        except Exception:
            logger.warning("Failed to delete consumed staging ref %s", ref, exc_info=True)


class EscalationResolution(BaseModel):
    escalation_id: str
    approved: bool
    comment: str = ""


class TaskCommandPayload(BaseModel):
    command: str
    model_instance_id: str | None = None
    budget_usd: Money | None = None
    message: str | None = None
    message_id: str | None = None


class ContinueTaskPayload(BaseModel):
    additional_iterations: int = Field(default=0, ge=0, le=1000)
    additional_budget_usd: Money | None = Field(default=None, gt=ZERO)

    model_config = {"extra": "forbid"}


@global_tasks_router.post("/{task_id}/continue")
async def continue_task_execution(
    task_id: UUID,
    payload: ContinueTaskPayload,
    user_context: UserContextDep,
    task_service: TaskService = Depends(get_task_service),
):
    """Grant more iterations or budget to a task waiting on a hard limit."""
    _ = user_context
    if payload.additional_iterations == 0 and payload.additional_budget_usd is None:
        raise HTTPException(
            status_code=422,
            detail="At least one continuation resource must be granted",
        )

    result = await task_service.continue_execution(
        task_id,
        additional_iterations=payload.additional_iterations,
        additional_budget_usd=payload.additional_budget_usd,
    )
    if result.get("reason") == "task_not_found":
        raise HTTPException(status_code=404, detail="Task not found")
    if not result.get("accepted"):
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Task is not waiting for continuation",
                "reason": result.get("reason", "continuation_rejected"),
            },
        )
    return result


_SECRET_NAME_SAFE_RE = re.compile(r"[^A-Za-z0-9_.:/-]+")


def _default_input_secret_name(task_id: UUID, field_name: str) -> str:
    """Build a stable workspace secret name for a submitted input field."""
    sanitized = _SECRET_NAME_SAFE_RE.sub("_", field_name).strip("._:/-")
    if not sanitized:
        sanitized = "secret"
    return f"task-input/{task_id}/{sanitized}"


def _failure_reason_from_result(result: Any) -> str | None:
    """Extract the stable failure code the workflow persisted into the result."""
    if isinstance(result, dict):
        value = result.get("failure_reason")
        if value:
            return str(value)
    return None


class TaskResponse(BaseModel):
    id: UUID
    agent_id: UUID
    description: str
    parameters: dict[str, Any]
    status: str
    result: dict[str, Any] | str | None = None
    # Terminal failure cause for a failed/blocked task. `error` is the durable
    # human-readable message (tasks.error column); `failure_reason` is a stable
    # code (validation_failed | iteration_limit | budget_exceeded | ...).
    error: str | None = None
    failure_reason: str | None = None
    created_at: UtcDatetime
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

    @classmethod
    def from_agent_task(cls, task: Any) -> "TaskResponse":
        """Build a response from a service-layer AgentTask, surfacing its failure cause."""
        return cls(
            id=task.id,
            agent_id=task.agent_id,
            description=task.description,
            parameters=task.task_parameters or {},
            status=task.status,
            result=task.result,
            error=task.error_message,
            failure_reason=_failure_reason_from_result(task.result),
            created_at=task.created_at,
            execution_id=task.execution_id,
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
    error: str | None = None
    failure_reason: str | None = None
    created_at: UtcDatetime
    execution_id: str | None = None
    total_cost: float | None = None  # LLM token cost in USD
    # Populated by the inbox endpoint for waiting_for_approval tasks so the UI can
    # approve/reject the pending escalation inline without re-fetching task events.
    escalation_id: str | None = None
    escalation_tool_name: str | None = None

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
            error=task.error,
            failure_reason=task.failure_reason,
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
        # Sequential awaits: agent_service and task_service share one AsyncSession
        # via ReadRepositoryFactoryDep, and asyncpg forbids concurrent ops on a
        # single connection ("another operation is in progress").
        agents_result = await agent_service.list()
        task_orms = await task_service.task_repository.list_all(limit=limit)

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
                    error=task.error,
                    failure_reason=_failure_reason_from_result(task.result),
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
        agent = await agent_service.get_with_catalog(task.agent_id)
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
            error=task.error,
            failure_reason=_failure_reason_from_result(task.result),
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
    timestamp: UtcDatetime
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


# Canonical terminal types (the vocabulary rows/streams now carry directly).
_TERMINAL_EVENT_TYPES = {
    TASK_COMPLETED,
    TASK_FAILED,
    TASK_CANCELLED,
}


async def _tail_task_events_sse(
    task_id: UUID,
    agent_id: UUID,
    execution_id: str | None,
    *,
    emit_connected: bool = True,
    include_chunks: bool = True,
) -> AsyncGenerator[str, None]:
    """Stream a task's events as SSE: catch-up (DB) then live (Redis stream).

    This is a CQRS read side (ADR-0018), not a poll of the write model. The
    full history is replayed from the durable ``task_events`` table (catch-up),
    then new events are tailed live from the per-task Redis stream the worker
    XADDs to. Dedup by event id makes the catch-up->live hand-off race-free, so
    a fast task whose events land before the reader attaches loses nothing
    (the old reason this used DB polling) — without the 0.25s poll.
    """
    from agentarea_api.api.v1.task_event_feed import open_task_event_feed

    if emit_connected:
        yield _format_sse_event(
            "connected",
            {
                "task_id": str(task_id),
                "agent_id": str(agent_id),
                "execution_id": execution_id,
                "message": "Connected to task event stream",
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )

    # Chunks are surfaced by default (include_chunks=True). Clients can opt out
    # via ?include_chunks=false, which drops the high-volume incremental
    # llm.call.chunk events.
    async for env in open_task_event_feed(
        task_id,
        terminal_types=frozenset(_TERMINAL_EVENT_TYPES),
        include_chunks=include_chunks,
    ):
        sse_event = {
            "event_type": env.event_type,
            "event_id": env.event_id,
            "timestamp": env.timestamp,
            "data": _filter_domain_fields(dict(env.data)),
        }
        yield _format_sse_event(env.event_type, sse_event)


@router.post("/")
async def create_task_for_agent_with_stream(
    agent_id: UUID,
    data: TaskCreate,
    user_context: UserContextDep,
    task_service: TaskService = Depends(get_task_service),
    agent_service: AgentService = Depends(get_agent_service),
):
    """Create and execute a task for the specified agent with real-time SSE stream."""
    # Verify agent exists. Built-in agents live in the registry catalog (ADR-003)
    # and are run directly from their definition (no fork on run), so accept a
    # catalog projection here too.
    agent = await agent_service.get_with_catalog(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    created_task = None
    if data.attachments:
        reserved_task_id = uuid4()
        attachment_descriptors = await _stage_attachments_into_task(
            user_context.workspace_id,
            reserved_task_id,
            data.attachments,
            user_context.user_id,
        )
        parameters = {**data.parameters, "attachments": attachment_descriptors}
        try:
            payload = RunCreate(
                agent_id=agent_id,
                description=data.description,
                parameters=parameters,
                execution=data.execution,
                requires_human_approval=data.requires_human_approval or False,
                project_id=data.project_id,
                task_policy=data.task_policy,
            )
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=exc.errors()) from exc

        try:
            created_task = await task_service.reserve_run(
                payload,
                workspace_id=user_context.workspace_id,
                user_id=user_context.user_id,
                task_id=reserved_task_id,
                trusted_metadata={"workspace_attachments": attachment_descriptors},
            )
        except PolicyValidationError as exc:
            raise HTTPException(status_code=422, detail="Task policy rejected") from exc
        except AgentModelNotConfiguredError as exc:
            raise HTTPException(status_code=422, detail="Agent model is not configured") from exc

        try:
            created_task = await task_service.dispatch_reserved_run(created_task)
        except Exception as exc:
            await task_service.update_task_status(
                reserved_task_id, "failed", error="Task dispatch failed"
            )
            logger.error("Failed to dispatch attachment task %s", reserved_task_id, exc_info=True)
            raise HTTPException(status_code=503, detail="Task dispatch failed") from exc

        # Consume the staging objects only now that the run is dispatched; a
        # failed dispatch above leaves them for a retry.
        await _delete_staging_refs(
            user_context.workspace_id, data.attachments, user_context.user_id
        )

    async def task_creation_stream() -> AsyncGenerator[str, None]:
        """Generate Server-Sent Events for task creation and execution."""
        task = created_task
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

            if task is None:
                # Create and execute task using service layer
                payload = RunCreate(
                    agent_id=agent_id,
                    description=data.description,
                    parameters=data.parameters,
                    execution=data.execution,
                    requires_human_approval=data.requires_human_approval or False,
                    project_id=data.project_id,
                    task_policy=data.task_policy,
                )
                task = await task_service.start_run(
                    payload,
                    workspace_id=user_context.workspace_id,
                    user_id=user_context.user_id,
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

            # Stream execution events by tailing the durable event log. We
            # already emitted "connected" above, so suppress the helper's own.
            # Tailing the DB (not Redis pub/sub) is what makes a fast task's
            # events show up: they are published before any subscriber could
            # attach, but they are durably logged, so replay is lossless.
            if task.execution_id and task.status in ["running", "pending"]:
                async for chunk in _tail_task_events_sse(
                    task.id, agent_id, task.execution_id, emit_connected=False
                ):
                    yield chunk
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

        except PolicyValidationError:
            yield _format_sse_event(
                "error",
                {
                    "agent_id": str(agent_id),
                    "error": "Task policy rejected",
                    "error_type": "policy_validation_error",
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )
        except AgentModelNotConfiguredError:
            yield _format_sse_event(
                "error",
                {
                    "agent_id": str(agent_id),
                    "error": "Agent model is not configured",
                    "error_type": "model_not_configured",
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
        except Exception:
            logger.error("Task creation failed")
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
        # Create and execute task using shared payload-style entry point so REST
        # /sync, REST streaming and MCP toolset all share the same lifecycle.
        if data.attachments:
            reserved_task_id = uuid4()
            attachment_descriptors = await _stage_attachments_into_task(
                user_context.workspace_id,
                reserved_task_id,
                data.attachments,
                user_context.user_id,
            )
            payload = RunCreate(
                agent_id=agent_id,
                description=data.description,
                parameters={**data.parameters, "attachments": attachment_descriptors},
                execution=data.execution,
                requires_human_approval=data.requires_human_approval or False,
                project_id=data.project_id,
                task_policy=data.task_policy,
            )
            task = await task_service.reserve_run(
                payload,
                workspace_id=user_context.workspace_id,
                user_id=user_context.user_id,
                task_id=reserved_task_id,
                trusted_metadata={"workspace_attachments": attachment_descriptors},
            )
            task = await task_service.dispatch_reserved_run(task)
            await _delete_staging_refs(
                user_context.workspace_id, data.attachments, user_context.user_id
            )
        else:
            payload = RunCreate(
                agent_id=agent_id,
                description=data.description,
                parameters=data.parameters,
                execution=data.execution,
                requires_human_approval=data.requires_human_approval or False,
                project_id=data.project_id,
                task_policy=data.task_policy,
            )
            task = await task_service.start_run(
                payload,
                workspace_id=user_context.workspace_id,
                user_id=user_context.user_id,
            )

        # Convert to API response format
        return TaskResponse.from_agent_task(task)

    except HTTPException:
        raise
    except PolicyValidationError as exc:
        raise HTTPException(status_code=422, detail="Task policy rejected") from exc
    except AgentModelNotConfiguredError as exc:
        raise HTTPException(status_code=422, detail="Agent model is not configured") from exc
    except ValueError as e:
        # Agent validation errors
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as exc:
        logger.error("Task creation failed")
        raise HTTPException(status_code=500, detail="Internal server error") from exc


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
            task_responses.append(TaskResponse.from_agent_task(task))

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
    task_service: TaskService = Depends(get_read_task_service),
    workflow_task_service: TemporalWorkflowService = Depends(get_temporal_workflow_service),
):
    """Get a specific task for the specified agent."""
    # Verify agent exists
    agent = await agent_service.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    try:
        task = await task_service.get_task_with_workflow_status(task_id)
        if task:
            if task.agent_id != agent_id:
                raise HTTPException(status_code=404, detail="Task not found")

            return TaskResponse.from_agent_task(task)

        # Fall back to workflow status for workflow-only tasks.
        execution_id = f"task-{task_id}"
        status = await workflow_task_service.get_workflow_status(execution_id)

        # If status indicates unknown, the task/workflow doesn't exist
        if status.get("status") == "unknown":
            raise HTTPException(status_code=404, detail="Task not found")

        # Convert workflow status to TaskResponse format
        return TaskResponse(
            id=task_id,
            agent_id=agent_id,
            description="Workflow-based task",  # Description not stored in workflow status
            parameters={},  # Parameters not stored in workflow status
            status=status.get("status", "unknown"),
            result=status.get("result"),
            error=status.get("error"),
            failure_reason=status.get("failure_reason"),
            created_at=datetime.now(UTC),  # Could be extracted from start_time if available
            execution_id=execution_id,
        )

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
    task_service: TaskService = Depends(get_read_task_service),
    workflow_task_service: TemporalWorkflowService = Depends(get_temporal_workflow_service),
):
    """Get the execution status of a specific task workflow."""
    # Verify agent exists
    agent = await agent_service.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    try:
        # DB is the source of truth for the task lifecycle; Temporal only
        # upgrades to a terminal state. The workflow may stay alive in
        # await_follow_up after writing "completed" to the DB, so reading the
        # raw live workflow status here would report "running" for a finished
        # task. get_task_with_workflow_status applies the same enrichment the
        # plain task get uses, keeping the two endpoints consistent.
        task = await task_service.get_task_with_workflow_status(task_id)
        if not task or str(task.agent_id) != str(agent_id):
            raise HTTPException(status_code=404, detail="Task not found")

        # Get workflow status for live execution detail (timing, session, etc.)
        execution_id = task.execution_id or f"task-{task_id}"
        status = await workflow_task_service.get_workflow_status(execution_id)
        stored_artifacts = await _list_task_artifact_items(
            agent_id=agent_id,
            workspace_id=user_context.workspace_id,
            task_id=task_id,
        )
        status_artifacts = status.get("artifacts") or []
        if stored_artifacts:
            status_artifacts = [item.model_dump() for item in stored_artifacts]

        return {
            "task_id": str(task_id),
            "agent_id": str(agent_id),
            "execution_id": execution_id,
            # Authoritative lifecycle status/result come from the persisted task.
            "status": task.status,
            "execution_status": status.get("execution_status", status.get("status")),
            "success": status.get("success"),
            "failure_reason": status.get("failure_reason"),
            "start_time": status.get("start_time"),
            "end_time": status.get("end_time"),
            "execution_time": status.get("execution_time"),
            "error": task.error_message,
            "result": task.result if task.result is not None else status.get("result"),
            # A2A-compatible fields for frontend
            "message": status.get("message"),
            "artifacts": status_artifacts,
            "session_id": status.get("session_id"),
            "usage_metadata": status.get("usage_metadata"),
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error") from e


class TaskArtifactItem(BaseModel):
    """A file explicitly published from a live task sandbox."""

    id: str
    path: str
    name: str
    size: int
    content_type: str | None
    sha256: str | None
    created_at: datetime | None
    download_url: str


class _ManagerArtifact(BaseModel):
    id: str
    path: str
    name: str
    size: int
    content_type: str = ""
    sha256: str = ""
    created_at: datetime | None = None


class _ManagerArtifactList(BaseModel):
    items: list[_ManagerArtifact]


class SandboxFileItem(BaseModel):
    path: str


class SandboxFileListResponse(BaseModel):
    items: list[SandboxFileItem]
    total: int


class _ManagerSandboxFileList(BaseModel):
    paths: list[str]


async def _sandbox_manager_request(
    method: str,
    path: str,
    *,
    params: dict[str, str] | None = None,
) -> httpx.Response:
    settings = get_settings().mcp
    secret = settings.SANDBOX_FILE_AUTH_SECRET
    if secret is None or not secret.get_secret_value():
        raise HTTPException(status_code=503, detail="Sandbox file access is not configured")
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            return await client.request(
                method,
                f"{settings.MCP_MANAGER_URL.rstrip('/')}{path}",
                params=params,
                headers={"Authorization": f"Bearer {secret.get_secret_value()}"},
            )
    except httpx.RequestError as exc:
        logger.warning("Sandbox manager request failed: %s", exc)
        raise HTTPException(
            status_code=503, detail="Sandbox file access is temporarily unavailable"
        ) from exc


async def _sandbox_manager_stream(
    path: str,
    *,
    params: dict[str, str],
) -> tuple[httpx.AsyncClient, httpx.Response]:
    settings = get_settings().mcp
    secret = settings.SANDBOX_FILE_AUTH_SECRET
    if secret is None or not secret.get_secret_value():
        raise HTTPException(status_code=503, detail="Sandbox file access is not configured")

    client = httpx.AsyncClient(timeout=300)
    request = client.build_request(
        "GET",
        f"{settings.MCP_MANAGER_URL.rstrip('/')}{path}",
        params=params,
        headers={"Authorization": f"Bearer {secret.get_secret_value()}"},
    )
    try:
        response = await client.send(request, stream=True)
    except httpx.RequestError as exc:
        await client.aclose()
        logger.warning("Sandbox manager streaming request failed: %s", exc)
        raise HTTPException(
            status_code=503, detail="Sandbox file access is temporarily unavailable"
        ) from exc
    return client, response


async def _stream_manager_download(
    client: httpx.AsyncClient,
    response: httpx.Response,
    *,
    resource: str,
    filename: str,
    default_content_type: str,
) -> StreamingResponse:
    if response.status_code >= 400:
        try:
            await response.aread()
            _raise_sandbox_manager_error(response, resource=resource)
        finally:
            await response.aclose()
            await client.aclose()

    async def stream_content() -> AsyncGenerator[bytes, None]:
        try:
            async for chunk in response.aiter_bytes():
                yield chunk
        finally:
            await response.aclose()
            await client.aclose()

    headers = {
        "Content-Disposition": response.headers.get(
            "content-disposition", _attachment_content_disposition(filename)
        )
    }
    if content_length := response.headers.get("content-length"):
        headers["Content-Length"] = content_length
    return StreamingResponse(
        stream_content(),
        media_type=response.headers.get("content-type", default_content_type),
        headers=headers,
    )


def _raise_sandbox_manager_error(response: httpx.Response, *, resource: str) -> None:
    if response.status_code == 404:
        raise HTTPException(status_code=404, detail=f"{resource} not found")
    if response.status_code == 410:
        raise HTTPException(status_code=410, detail="Sandbox workspace has expired")
    if response.status_code >= 400:
        logger.warning(
            "Sandbox manager %s request returned %s: %s",
            resource,
            response.status_code,
            response.text[:300],
        )
        raise HTTPException(
            status_code=503, detail="Sandbox file access is temporarily unavailable"
        )


async def _list_task_artifact_items(
    *,
    agent_id: UUID,
    workspace_id: str,
    task_id: UUID,
) -> list[TaskArtifactItem]:
    response = await _sandbox_manager_request(
        "GET",
        "/sandbox/artifacts",
        params={"workspace_id": workspace_id, "task_id": str(task_id)},
    )
    _raise_sandbox_manager_error(response, resource="Artifact list")
    try:
        result = _ManagerArtifactList.model_validate(response.json())
    except (ValueError, ValidationError) as exc:
        logger.error("Sandbox manager returned an invalid artifact list: %s", exc)
        raise HTTPException(status_code=502, detail="Artifact list response is invalid") from exc
    return [
        TaskArtifactItem(
            id=item.id,
            path=item.path,
            name=item.name,
            size=item.size,
            content_type=item.content_type or None,
            sha256=item.sha256 or None,
            created_at=item.created_at,
            download_url=_task_artifact_download_url(agent_id, task_id, item.id),
        )
        for item in result.items
    ]


def _task_artifact_download_url(agent_id: UUID, task_id: UUID, artifact_id: str) -> str:
    return f"/v1/agents/{agent_id}/tasks/{task_id}/artifacts/files/{artifact_id}"


async def _verify_task_for_agent(task_service: TaskService, agent_id: UUID, task_id: UUID) -> Any:
    task = await task_service.get_task(task_id)
    if not task or str(task.agent_id) != str(agent_id):
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.get("/{task_id}/artifacts", response_model=list[TaskArtifactItem])
async def list_task_artifacts(
    agent_id: UUID,
    task_id: UUID,
    user_context: UserContextDep,
    expires_in: int = Query(3600, ge=60, le=86400),
    task_service: TaskService = Depends(get_read_task_service),
) -> list[TaskArtifactItem]:
    """List files the agent explicitly published as durable artifacts.

    Workspace-scoped: the task must belong to the caller's workspace, or we
    return 404. Each item carries an AgentArea API download URL, so access
    stays behind our auth, audit, and workspace checks instead of exposing
    object-storage URLs directly.
    """
    _ = expires_in  # Backwards-compatible no-op; API-controlled links do not expire here.
    await _verify_task_for_agent(task_service, agent_id, task_id)

    return await _list_task_artifact_items(
        agent_id=agent_id,
        workspace_id=user_context.workspace_id,
        task_id=task_id,
    )


@router.get("/{task_id}/artifacts/files/{artifact_path:path}")
async def download_task_artifact(
    agent_id: UUID,
    task_id: UUID,
    artifact_path: str,
    user_context: UserContextDep,
    task_service: TaskService = Depends(get_read_task_service),
):
    """Stream a task artifact through the AgentArea API."""
    await _verify_task_for_agent(task_service, agent_id, task_id)
    if not re.fullmatch(r"art_[0-9a-f]{32}", artifact_path):
        raise HTTPException(status_code=404, detail="Artifact not found")
    client, response = await _sandbox_manager_stream(
        f"/sandbox/artifacts/{artifact_path}",
        params={"workspace_id": user_context.workspace_id, "task_id": str(task_id)},
    )
    return await _stream_manager_download(
        client,
        response,
        resource="Artifact",
        filename=artifact_path,
        default_content_type="application/octet-stream",
    )


def _normalize_live_sandbox_path(value: str, *, allow_empty: bool = False) -> str:
    if allow_empty and value == "":
        return ""
    if not value or value.startswith("/") or "\\" in value or "\x00" in value:
        raise HTTPException(status_code=422, detail="Sandbox path must be relative")
    parts = PurePosixPath(value).parts
    if any(part in {"", ".", ".."} for part in parts):
        raise HTTPException(status_code=422, detail="Sandbox path must be relative")
    return "/".join(parts)


@router.get("/{task_id}/sandbox/files", response_model=SandboxFileListResponse)
async def list_task_sandbox_files(
    agent_id: UUID,
    task_id: UUID,
    user_context: UserContextDep,
    prefix: str = Query(""),
    task_service: TaskService = Depends(get_read_task_service),
) -> SandboxFileListResponse:
    """Inspect regular files in the existing live sandbox without recreating it."""
    await _verify_task_for_agent(task_service, agent_id, task_id)
    normalized_prefix = _normalize_live_sandbox_path(prefix, allow_empty=True)
    response = await _sandbox_manager_request(
        "GET",
        "/sandbox/files",
        params={
            "workspace_id": user_context.workspace_id,
            "task_id": str(task_id),
            "list": normalized_prefix,
            "ensure": "false",
        },
    )
    _raise_sandbox_manager_error(response, resource="Sandbox workspace")
    try:
        result = _ManagerSandboxFileList.model_validate(response.json())
    except (ValueError, ValidationError) as exc:
        logger.error("Sandbox manager returned an invalid file list: %s", exc)
        raise HTTPException(status_code=502, detail="Sandbox file list is invalid") from exc
    items = [SandboxFileItem(path=path) for path in result.paths]
    return SandboxFileListResponse(items=items, total=len(items))


@router.get("/{task_id}/sandbox/files/{file_path:path}")
async def read_task_sandbox_file(
    agent_id: UUID,
    task_id: UUID,
    file_path: str,
    user_context: UserContextDep,
    task_service: TaskService = Depends(get_read_task_service),
):
    """Read one file from the existing live sandbox without recreating it."""
    await _verify_task_for_agent(task_service, agent_id, task_id)
    normalized = _normalize_live_sandbox_path(file_path)
    client, response = await _sandbox_manager_stream(
        "/sandbox/file-content",
        params={
            "workspace_id": user_context.workspace_id,
            "task_id": str(task_id),
            "path": normalized,
            "ensure": "false",
        },
    )
    content_type = mimetypes.guess_type(normalized)[0] or "application/octet-stream"
    return await _stream_manager_download(
        client,
        response,
        resource="Sandbox file",
        filename=PurePosixPath(normalized).name,
        default_content_type=content_type,
    )


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
    started_at: UtcDatetime | None = None
    ended_at: UtcDatetime | None = None
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
        (
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
        )
        .mappings()
        .first()
    )

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


@router.post("/{task_id}/input")
async def submit_task_input(
    agent_id: UUID,
    task_id: UUID,
    submission: TaskInputSubmission,
    user_context: UserContextDep,
    secret_manager: BaseSecretManagerDep,
    agent_service: AgentService = Depends(get_agent_service),
    workflow_task_service: TemporalWorkflowService = Depends(get_temporal_workflow_service),
):
    """Submit structured user input to a workflow waiting on request_user_input.

    Secret values are written to the workspace secret manager at the API boundary.
    Only secret refs are sent to Temporal/LLM context.
    """
    agent = await agent_service.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    execution_id = f"task-{task_id}"

    try:
        status = await workflow_task_service.get_workflow_status(execution_id)
        if status.get("status") == "unknown":
            raise HTTPException(status_code=404, detail="Task not found")

        current_status = status.get("status", "").lower()
        if current_status in ["completed", "failed", "cancelled"]:
            raise HTTPException(
                status_code=400, detail=f"Cannot submit input to task in '{current_status}' state"
            )

        secret_refs: dict[str, dict[str, str]] = {}
        for field_name, raw_secret in submission.secrets.items():
            if isinstance(raw_secret, InputSecretValue):
                secret_value = raw_secret.value
                secret_name = raw_secret.secret_name or _default_input_secret_name(
                    task_id, field_name
                )
            else:
                secret_value = str(raw_secret)
                secret_name = _default_input_secret_name(task_id, field_name)

            await secret_manager.set_secret(secret_name, secret_value)
            secret_refs[field_name] = {
                "secret_name": secret_name,
                "secret_ref": f"secret:{secret_name}",
            }

        payload = {
            "input_request_id": submission.input_request_id,
            "answers": submission.answers,
            "secret_refs": secret_refs,
            "submitted_by": str(user_context.user_id),
        }
        success = await workflow_task_service.send_workflow_command(
            execution_id, "submit_user_input", payload
        )
        if not success:
            raise HTTPException(status_code=500, detail="Failed to submit input to workflow")

        return {
            "status": "accepted",
            "task_id": str(task_id),
            "input_request_id": submission.input_request_id,
            "answer_keys": sorted(submission.answers.keys()),
            "secret_keys": sorted(secret_refs.keys()),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to submit input for task {task_id}: {e}", exc_info=True)
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
    if not provider_config or not provider_spec or not model_spec:
        raise HTTPException(
            status_code=409,
            detail="Model instance has incomplete provider or model configuration",
        )

    return {
        "model_id": str(instance.id),
        "provider_type": provider_spec.provider_type,
        "model_name": model_spec.model_name,
        "api_key_secret": provider_config.api_key,
        "endpoint_url": provider_config.endpoint_url,
        "context_window": model_spec.context_window,
        "max_output_tokens": model_spec.max_output_tokens,
        "input_cost_per_token": model_spec.input_cost_per_token,
        "output_cost_per_token": model_spec.output_cost_per_token,
        "display_name": model_spec.display_name,
        "provider_display_name": provider_spec.name,
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
            delivered = await workflow_task_service.send_workflow_command(
                execution_id, "change_model", resolved
            )

        elif payload.command == "queue_message":
            if not payload.message:
                raise HTTPException(status_code=400, detail="message is required for queue_message")
            delivered = await workflow_task_service.send_workflow_command(
                execution_id, "queue_message", {"message": payload.message}
            )

        elif payload.command == "remove_message":
            if not payload.message_id:
                raise HTTPException(
                    status_code=400, detail="message_id is required for remove_message"
                )
            delivered = await workflow_task_service.send_workflow_command(
                execution_id, "remove_message", {"message_id": payload.message_id}
            )

        elif payload.command == "update_budget":
            if payload.budget_usd is None:
                raise HTTPException(
                    status_code=400, detail="budget_usd is required for update_budget"
                )
            delivered = await workflow_task_service.send_workflow_command(
                execution_id,
                "update_budget",
                {"budget_usd": serialize_money(payload.budget_usd)},
            )

        else:
            raise HTTPException(status_code=400, detail=f"Unknown command: {payload.command}")

        # send_workflow_command returns False when the signal could not be
        # delivered — most commonly because the task's workflow is no longer
        # running (completed / timed out / terminated). Surface that as a real
        # error instead of a misleading 200, so the UI doesn't claim a change
        # (e.g. a model switch) that never actually happened.
        if not delivered:
            raise HTTPException(
                status_code=409,
                detail="Task is not running; the command could not be delivered to its workflow.",
            )

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
            execution_id,
            data.escalation_id,
            data.approved,
            data.comment,
            resolved_by=str(user_context.user_id),
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
    repository_factory: ReadRepositoryFactoryDep,
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
        # Read through the workspace-scoped repository. The check above only
        # proves the caller owns an agent with this id — `agent_id` is a route
        # parameter and is never tied to the task — so the workspace filter
        # inside the repository is the actual authorization boundary here.
        event_repository = repository_factory.create_repository(TaskEventRepository)
        records, total_events = await event_repository.list_for_task(
            task_id,
            event_type=event_type,
            limit=page_size,
            offset=(page - 1) * page_size,
        )

        events = [
            TaskEvent(
                id=str(record.id),
                task_id=str(record.task_id),
                agent_id=str(agent_id),
                execution_id=record.data.get("execution_id")
                or record.metadata.get("execution_id", "unknown"),
                timestamp=record.timestamp,
                event_type=record.event_type,
                message=record.data.get("message", f"Event: {record.event_type}"),
                metadata=dict(record.data) if record.data else {},
            )
            for record in records
        ]

        return TaskEventResponse(
            events=events,
            total=total_events,
            page=page,
            page_size=page_size,
            has_next=(page * page_size) < total_events,
        )

    except Exception as e:
        logger.error(f"Failed to get task events for task {task_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.get("/{task_id}/events/stream")
async def stream_task_events(
    agent_id: UUID,
    task_id: UUID,
    user_context: UserContextDep,
    include_chunks: bool = Query(
        True, description="Include incremental llm.call.chunk token events in the stream"
    ),
    agent_service: AgentService = Depends(get_read_agent_service),
    task_service: TaskService = Depends(get_read_task_service),
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

        # Create SSE stream by tailing the task_events table (single source of
        # truth, no pub/sub race) via the shared helper.
        async def event_stream() -> AsyncGenerator[str, None]:
            try:
                async for chunk in _tail_task_events_sse(
                    task_id, agent_id, task.execution_id, include_chunks=include_chunks
                ):
                    yield chunk

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
    #   "event_type": "llm.call.chunk",
    #   "data": {
    #       "aggregate_id": "...",
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
