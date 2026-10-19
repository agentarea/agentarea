import asyncio
import json
import logging
import mimetypes
import re
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any
from uuid import UUID, uuid4

import httpx
from agentarea_agents.application.agent_service import AgentService
from agentarea_agents.application.execution_service import (
    EscalationNotPendingError,
    NotAnApproverError,
    WorkflowNotFoundError,
)
from agentarea_agents.application.temporal_workflow_service import (
    TemporalWorkflowService,
)
from agentarea_api.api.deps.services import (
    BaseSecretManagerDep,
    get_agent_service,
    get_model_instance_service,
    get_read_agent_service,
    get_read_task_service,
    get_task_service,
    get_temporal_workflow_service,
)
from agentarea_common.artifacts import secure_download_headers
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.dependencies import UserContextDep
from agentarea_common.auth.route_authz import enforced_in_handler, unrestricted
from agentarea_common.base import ReadRepositoryFactoryDep
from agentarea_common.base.pagination import MAX_OFFSET, MAX_PAGE
from agentarea_common.config import get_settings
from agentarea_common.events.contract import (
    EXECUTION_FINISHED,
    TASK_CANCELLED,
    TASK_COMPLETED,
    TASK_FAILED,
    TOOL_CALL,
    TOOL_RESULT,
)
from agentarea_common.extensions.customer_pricing import get_customer_pricing
from agentarea_common.money import ZERO, Money, serialize_money
from agentarea_common.reserved_task_parameters import reject_reserved_parameters
from agentarea_common.utils.task_webhook import TASK_WEBHOOK_KEY, webhook_secret_name
from agentarea_common.utils.types import UtcDatetime, utc_isoformat
from agentarea_common.utils.url_safety import OutboundPolicy
from agentarea_common.workflow.executor import WorkflowStatus
from agentarea_common.workspaces.lookup import workspace_api_prefix
from agentarea_governance.domain.policies import PolicyDocument, PolicyValidationError
from agentarea_llm.application.model_instance_service import ModelInstanceService
from agentarea_llm.domain.model_kind import ModelKind
from agentarea_mcp.tool_context import APP_METADATA_KEY, END_USER_ID_KEY
from agentarea_openapi.application.url_validator import validate_url
from agentarea_secrets.naming import has_reserved_prefix
from agentarea_tasks.domain.exceptions import (
    AgentModelNotConfiguredError,
    BudgetCapExceededError,
    RunStillClosingError,
    SchedulingNotSupportedError,
)
from agentarea_tasks.domain.feed import feed_event
from agentarea_tasks.domain.models import TaskProvenance
from agentarea_tasks.domain.statuses import ENDED_TASK_STATUSES, TaskStatus
from agentarea_tasks.infrastructure.repository import TaskRepository
from agentarea_tasks.infrastructure.task_log import TaskFeedReader
from agentarea_tasks.schemas.dto import RunCreate, RunExecutionConfig, require_future_instant
from agentarea_tasks.task_service import TaskService
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from ._task_authority import (
    caller_may_act_on_task,
    may_resolve_escalation,
    requires_task_authority,
)

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

# Bound on TaskCreate.metadata: it rides in every signed tool-call token.
TASK_METADATA_MAX_BYTES = 4096

# Global tasks router (not agent-specific)
global_tasks_router = APIRouter(prefix="/tasks", tags=["tasks"])


class TaskWebhook(BaseModel):
    """Where to POST each terminal event of the task, with its cost."""

    url: str = Field(min_length=1, max_length=2048, description="http(s) URL to POST to.")
    secret: str | None = Field(
        default=None,
        min_length=32,
        max_length=512,
        description=(
            "Signs each delivery as X-AgentArea-Signature: t=<unix>,v1=<hex HMAC-SHA256 "
            'of "<t>.<body>">. Write-only: stored in the secret manager.'
        ),
    )

    model_config = {"extra": "forbid"}


def _is_api_caller(user_context: UserContext) -> bool:
    """An API key or service client: who may set, and read back, caller context."""
    return user_context.api_key_id is not None or user_context.client_id is not None


class TaskCreate(BaseModel):
    description: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    _reject_reserved_parameters = field_validator("parameters")(reject_reserved_parameters)
    execution: RunExecutionConfig | None = None
    requires_human_approval: bool | None = False
    project_id: str | None = None
    task_policy: PolicyDocument | None = None
    # staging refs from a presigned POST /v1/files/upload-url
    attachments: list[str] | None = None
    # Trusted context for the task's tool calls, asserted by the API caller (an
    # API key or service client, never a browser session and never the model).
    # Every MCP server with a context signing secret receives them, signed, as
    # agentarea/metadata and agentarea/end_user_id.
    metadata: dict[str, Any] | None = Field(
        default=None,
        description=(
            'Trusted task metadata for tool servers, e.g. {"chatId": "..."}. '
            f"At most {TASK_METADATA_MAX_BYTES} bytes of JSON. Only API keys and "
            "service clients may set it."
        ),
    )
    end_user_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=256,
        description=(
            "The caller's own id for the end user this task runs for. Only API "
            "keys and service clients may set it."
        ),
    )
    webhook: TaskWebhook | None = Field(
        default=None,
        description=(
            "POSTed on task.completed, task.failed and task.cancelled with the task's "
            "total_cost, tokens_used, end_user_id and metadata. Only API keys and "
            "service clients may set it."
        ),
    )

    @field_validator("metadata")
    @classmethod
    def _bound_metadata(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is None:
            return value
        try:
            size = len(json.dumps(value, separators=(",", ":")).encode("utf-8"))
        except (TypeError, ValueError) as exc:
            raise ValueError("metadata must be JSON-serializable") from exc
        if size > TASK_METADATA_MAX_BYTES:
            raise ValueError(f"metadata must be at most {TASK_METADATA_MAX_BYTES} bytes of JSON")
        return value

    def trusted_metadata(self, user_context: UserContext) -> dict[str, Any]:
        """The caller-asserted context as task metadata; refuses a session caller."""
        if self.metadata is None and self.end_user_id is None and self.webhook is None:
            return {}
        if not _is_api_caller(user_context):
            raise HTTPException(
                status_code=403,
                detail="metadata, end_user_id and webhook can only be set with an API key",
            )
        trusted: dict[str, Any] = {}
        if self.metadata is not None:
            trusted[APP_METADATA_KEY] = self.metadata
        if self.end_user_id is not None:
            trusted[END_USER_ID_KEY] = self.end_user_id
        if self.webhook is not None:
            # The API caller is a workspace principal, so the deployment's
            # outbound policy applies, as for the workspace's own MCP endpoints.
            try:
                validate_url(self.webhook.url, policy=OutboundPolicy.from_env())
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=f"webhook.url: {exc}") from exc
            trusted[TASK_WEBHOOK_KEY] = {
                "url": self.webhook.url,
                "signed": self.webhook.secret is not None,
            }
        return trusted

    async def store_webhook_secret(self, secret_manager: Any, task_id: UUID | str) -> None:
        """Keep the webhook's signing secret where the delivery reads it."""
        if self.webhook is not None and self.webhook.secret is not None:
            await secret_manager.set_secret(webhook_secret_name(str(task_id)), self.webhook.secret)

    @model_validator(mode="before")
    @classmethod
    def _refuse_a_schedule(cls, data: Any) -> Any:
        # Unknown fields are ignored, so a scheduled_at sent here used to be
        # dropped and the task started at once. Only /tasks/schedule takes one.
        if cls is TaskCreate and isinstance(data, dict) and "scheduled_at" in data:
            raise ValueError("scheduled_at is not accepted here; use POST .../tasks/schedule")
        return data


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

    Each ref (``staging/{id}/{filename}`` from a presigned
    ``POST /v1/files/upload-url``) is HEADed to resolve its verified sha256,
    size and content type, then copied server-side into the task's
    content-addressed store via ``attach_object``. The bytes never transit
    this process. Returns the attachment descriptors persisted alongside the
    run. Raises HTTP errors mirroring the
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
    additional_tokens: int = Field(default=0, ge=0, le=10_000_000)
    additional_tool_calls: int = Field(default=0, ge=0, le=10_000)

    model_config = {"extra": "forbid"}

    @property
    def grants_nothing(self) -> bool:
        return (
            self.additional_iterations == 0
            and self.additional_budget_usd is None
            and self.additional_tokens == 0
            and self.additional_tool_calls == 0
        )


@global_tasks_router.post(
    "/{task_id}/continue",
    dependencies=[requires_task_authority()],
)
async def continue_task_execution(
    task_id: UUID,
    payload: ContinueTaskPayload,
    user_context: UserContextDep,
    task_service: TaskService = Depends(get_task_service),
):
    """Grant more iterations, budget, tokens or tool calls to a task waiting on a hard limit."""
    _ = user_context
    if payload.grants_nothing:
        raise HTTPException(
            status_code=422,
            detail="At least one continuation resource must be granted",
        )

    result = await task_service.continue_execution(
        task_id,
        additional_iterations=payload.additional_iterations,
        additional_budget_usd=payload.additional_budget_usd,
        additional_tokens=payload.additional_tokens,
        additional_tool_calls=payload.additional_tool_calls,
    )
    if result.get("reason") == "task_not_found":
        raise HTTPException(status_code=404, detail="Task not found")
    if not result.get("accepted"):
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Continuation was not accepted",
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


def _failure_reason_from_result(result: Any, metadata: Any = None) -> str | None:
    """The stable failure code the workflow stored: in the task's metadata, or in a result."""
    for source in (metadata, result):
        if isinstance(source, dict) and source.get("failure_reason"):
            return str(source["failure_reason"])
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
    # Model tokens the task has used so far; set once a turn has ended.
    total_tokens: int | None = None
    # What the API caller set at creation. Returned to API keys and service
    # clients only, the callers allowed to set them; null for anyone else.
    end_user_id: str | None = None
    metadata: dict[str, Any] | None = None
    # Set only on one-shot deferred runs; null means the task ran on creation.
    scheduled_at: UtcDatetime | None = None
    # Who started the task. Distinct from `parameters`-derived source: a
    # trigger-fired task is still owned by whoever created the trigger.
    created_by: str | None = None
    # Who or what started the task and the event that caused it: a trigger and
    # its stream event, a delegating agent, a person, the API.
    provenance: TaskProvenance = Field(default_factory=TaskProvenance)

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
    def from_agent_task(cls, task: Any, user_context: UserContext | None = None) -> "TaskResponse":
        """Build a response from a service-layer AgentTask, surfacing its failure cause."""
        return cls(
            id=task.id,
            agent_id=task.agent_id,
            description=task.description,
            parameters=task.task_parameters or {},
            status=task.status,
            result=task.result,
            error=task.error_message,
            failure_reason=_failure_reason_from_result(task.result, task.metadata),
            created_at=task.created_at,
            execution_id=task.execution_id,
            scheduled_at=task.scheduled_at,
            created_by=task.user_id,
            provenance=task.provenance,
            **_usage_fields(task.result),
            **_caller_fields(getattr(task, "metadata", None), user_context),
        )


def _usage_fields(result: Any) -> dict[str, Any]:
    """total_cost and total_tokens as the workflow stored them in the task result."""
    if not isinstance(result, dict):
        return {}
    fields: dict[str, Any] = {}
    if result.get("total_cost") is not None:
        fields["total_cost"] = result["total_cost"]
    if isinstance(result.get("tokens_used"), int):
        fields["total_tokens"] = result["tokens_used"]
    return fields


def _caller_fields(metadata: Any, user_context: UserContext | None) -> dict[str, Any]:
    """end_user_id and metadata, for the callers that may set them."""
    if user_context is None or not _is_api_caller(user_context) or not isinstance(metadata, dict):
        return {}
    return {
        "end_user_id": metadata.get(END_USER_ID_KEY),
        "metadata": metadata.get(APP_METADATA_KEY),
    }


class TaskWithAgent(BaseModel):
    """Task response with agent information for global task listing."""

    id: UUID
    agent_id: UUID
    # None when the task's agent no longer resolves. Never substitute a
    # placeholder name: a fabricated "Unknown" is indistinguishable from an
    # agent actually called that, and it hides the missing agent from the UI.
    agent_name: str | None = None
    description: str
    parameters: dict[str, Any]
    status: str
    result: dict[str, Any] | str | None = None
    error: str | None = None
    failure_reason: str | None = None
    created_at: UtcDatetime
    execution_id: str | None = None
    total_cost: float | None = None  # LLM token cost in USD
    total_tokens: int | None = None
    # API keys and service clients only, as on TaskResponse.
    end_user_id: str | None = None
    metadata: dict[str, Any] | None = None
    scheduled_at: UtcDatetime | None = None
    # Populated by the inbox endpoint for waiting_for_approval tasks so the UI can
    # approve/reject the pending escalation inline without re-fetching task events.
    escalation_id: str | None = None
    escalation_tool_name: str | None = None
    # The principal that started the task. Only the id: resolving it to a name
    # is GET /v1/principals' job, so a task never fails to load because the
    # identity provider is slow.
    created_by: str | None = None
    # Who or what started the task and the event that caused it: a trigger and
    # its stream event, a delegating agent, a person, the API.
    provenance: TaskProvenance = Field(default_factory=TaskProvenance)

    @classmethod
    def from_task_response(
        cls,
        task: TaskResponse,
        agent_name: str | None,
    ) -> "TaskWithAgent":
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
            total_tokens=task.total_tokens,
            end_user_id=task.end_user_id,
            metadata=task.metadata,
            scheduled_at=task.scheduled_at,
            created_by=task.created_by,
            provenance=task.provenance,
        )


@global_tasks_router.get(
    "/",
    response_model=list[TaskWithAgent],
    dependencies=[
        unrestricted("workspace member; the workspace-scoped repository is the boundary")
    ],
)
async def get_all_tasks(
    user_context: UserContextDep,
    status: list[TaskStatus] | None = Query(
        None, description="Filter to tasks in any of these statuses"
    ),
    created_by: str | None = Query(None, description="Filter by the principal that started it"),
    search: str | None = Query(
        None, description="Case-insensitive match on the description or the agent name"
    ),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of tasks to return"),
    offset: int = Query(0, ge=0, le=MAX_OFFSET, description="Number of tasks to skip"),
    agent_service: AgentService = Depends(get_read_agent_service),
    task_service: TaskService = Depends(get_read_task_service),
):
    """Get one page of the workspace's tasks across all agents, newest first.

    Access Control:
        Returns all tasks within the current user's workspace (workspace isolation).
        All users in the same workspace can see all workspace tasks.
    """
    try:
        # Sequential awaits: agent_service and task_service share one AsyncSession
        # via ReadRepositoryFactoryDep, and asyncpg forbids concurrent ops on a
        # single connection ("another operation is in progress").
        agents_result = await agent_service.list()
        agent_map = {str(agent.id): agent.name for agent in agents_result}
        task_orms = await task_service.task_repository.list_page(
            limit=limit,
            offset=offset,
            statuses=status or [],
            created_by=created_by,
            search=search,
            agent_ids=[
                agent.id
                for agent in agents_result
                if search and search.lower() in (agent.name or "").lower()
            ],
        )

        all_tasks: list[TaskWithAgent] = []
        for task_orm in task_orms:
            task = task_service.task_repository._orm_to_domain(task_orm)
            all_tasks.append(
                TaskWithAgent(
                    id=task.id,
                    agent_id=task.agent_id,
                    agent_name=agent_map.get(str(task.agent_id)),
                    description=task.description,
                    parameters=task.parameters,
                    status=task.status,
                    result=task.result,
                    error=task.error,
                    failure_reason=_failure_reason_from_result(task.result, task.metadata),
                    created_at=task.created_at,
                    scheduled_at=task.scheduled_at,
                    execution_id=task.execution_id,
                    created_by=task.user_id,
                    provenance=task.provenance,
                    **_usage_fields(task.result),
                    **_caller_fields(task.metadata, user_context),
                )
            )
        return all_tasks

    except Exception as e:
        logger.exception(f"Failed to get all tasks: {e}")
        raise HTTPException(status_code=500, detail="Internal server error") from e


@global_tasks_router.get(
    "/{task_id}",
    response_model=TaskWithAgent,
    dependencies=[
        unrestricted("workspace member; the workspace-scoped repository is the boundary")
    ],
)
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
        return TaskWithAgent(
            id=task.id,
            agent_id=task.agent_id,
            agent_name=agent.name if agent else None,
            description=task.description,
            parameters=task.parameters,
            status=task.status,
            result=task.result,
            error=task.error,
            failure_reason=_failure_reason_from_result(task.result, task.metadata),
            created_at=task.created_at,
            scheduled_at=task.scheduled_at,
            execution_id=task.execution_id,
            created_by=task.user_id,
            provenance=task.provenance,
            **_usage_fields(task.result),
            **_caller_fields(task.metadata, user_context),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to get task {task_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error") from e


class TaskEvent(BaseModel):
    """Model for task execution events."""

    id: str
    task_id: str
    agent_id: str
    # None for events recorded outside a workflow execution. "unknown" was a
    # fabricated id that callers could not tell apart from a real one.
    execution_id: str | None = None
    timestamp: UtcDatetime
    event_type: str
    message: str | None = None
    # Same as `id`; the name the live stream uses.
    event_id: str | None = None
    # The entry's position in the task log; the SSE id a reconnect resumes after.
    seq: int | None = None
    # The event payload, shaped exactly like `data` on the live stream.
    data: dict[str, Any] = {}
    # Deprecated alias: the stored payload before the live stream's flattening.
    # Kept for clients that read it; new clients read `data`.
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
    EXECUTION_FINISHED,
}


async def _tail_task_events_sse(
    task_id: UUID,
    agent_id: UUID,
    execution_id: str | None,
    *,
    user_context: UserContext,
    revealed: bool,
    emit_connected: bool = True,
    include_chunks: bool = True,
    last_event_id: str | None = None,
    follow_execution: bool = True,
) -> AsyncGenerator[str, None]:
    """Stream a task's feed as SSE: its log, then the ``tasks.events`` tail (ADR-0043 §8).

    Each stored entry carries its log ``seq`` as the SSE ``id``, so a
    reconnecting EventSource sends it back as ``Last-Event-ID`` and resumes
    after it. Live-only signals (chunks, a call started, progress) carry none.

    ``follow_execution`` keeps the stream open past a ``task.completed`` that
    leaves the execution waiting for a follow-up; without it that event ends it.
    ``revealed``: the caller holds the task's authority, decided once per
    connection; its tool calls show their command and output, secrets masked.
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
        user_context=user_context,
        terminal_types=frozenset(_TERMINAL_EVENT_TYPES),
        include_chunks=include_chunks,
        follow_execution=follow_execution,
        last_event_id=last_event_id,
        revealed=revealed,
    ):
        sse_event = {
            "event_type": env.event_type,
            "event_id": env.event_id,
            "timestamp": env.timestamp,
            "data": _filter_domain_fields(dict(env.data)),
        }
        if env.seq is not None:
            sse_event["seq"] = env.seq
        yield _format_sse_event(
            env.event_type, sse_event, event_id=str(env.seq) if env.seq is not None else None
        )


async def _with_sse_heartbeats(
    source: AsyncGenerator[str, None],
    *,
    interval_seconds: float = 15.0,
) -> AsyncGenerator[str, None]:
    """Emit ``: ping`` comments while ``source`` has no frame ready.

    One producer task iterates ``source`` for its whole life, so a deadline the
    source holds across ``yield`` (the event feed's wall-clock ``asyncio.timeout``)
    stays bound to a live task and still fires. The producer also runs
    ``source.aclose()``, in the task that iterated it.
    """
    frames: asyncio.Queue[str] = asyncio.Queue(maxsize=1)

    async def produce() -> None:
        try:
            async for frame in source:
                await frames.put(frame)
        finally:
            await source.aclose()

    producer = asyncio.create_task(produce())
    next_frame = asyncio.create_task(frames.get())
    try:
        while True:
            done, _ = await asyncio.wait(
                (next_frame, producer),
                timeout=interval_seconds,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if next_frame in done:
                yield next_frame.result()
                next_frame = asyncio.create_task(frames.get())
            elif producer in done:
                break
            else:
                yield ": ping\n\n"
        # Cancelling a pending Queue.get leaves its frame queued for the drain.
        next_frame.cancel()
        while not frames.empty():
            yield frames.get_nowait()
        # A producer cancelled here was cut by the source's own deadline while
        # it waited to hand over a frame: the stream ends like a timed-out feed.
        if not producer.cancelled():
            producer.result()
    finally:
        next_frame.cancel()
        if not producer.done():
            producer.cancel()
            # asyncio.wait, not gather: a repeated cancellation of this task must
            # not interrupt the producer's source.aclose().
            await asyncio.wait((producer,))
            if not producer.cancelled() and (error := producer.exception()) is not None:
                logger.error("SSE source failed while closing", exc_info=error)


@router.post(
    "/",
    dependencies=[
        unrestricted("workspace member; the workspace-scoped repository is the boundary")
    ],
)
async def create_task_for_agent_with_stream(
    agent_id: UUID,
    data: TaskCreate,
    user_context: UserContextDep,
    secret_manager: BaseSecretManagerDep,
    follow: bool = Query(
        False,
        description=(
            "Keep the stream open through the follow-up window (up to 30 minutes) "
            "and relay follow-up turns. By default the stream ends at the turn's "
            "terminal event (task.completed, task.failed, task.cancelled); read "
            "follow-ups from GET .../tasks/{task_id}/events/stream."
        ),
    ),
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
    caller_metadata = data.trusted_metadata(user_context)

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
            raise RequestValidationError(exc.errors()) from exc

        try:
            created_task = await task_service.reserve_run(
                payload,
                workspace_id=user_context.workspace_id,
                user_id=user_context.user_id,
                task_id=reserved_task_id,
                trusted_metadata={
                    **caller_metadata,
                    "workspace_attachments": attachment_descriptors,
                },
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

    creation_error: tuple[str, str] | None = None
    creation_error_details: dict[str, str | float] = {}
    if created_task is None:
        try:
            payload = RunCreate(
                agent_id=agent_id,
                description=data.description,
                parameters=data.parameters,
                execution=data.execution,
                requires_human_approval=data.requires_human_approval or False,
                project_id=data.project_id,
                task_policy=data.task_policy,
            )
        except ValidationError as exc:
            raise RequestValidationError(exc.errors()) from exc
        try:
            created_task = await task_service.start_run(
                payload,
                workspace_id=user_context.workspace_id,
                user_id=user_context.user_id,
                trusted_metadata=caller_metadata or None,
            )
        except PolicyValidationError:
            creation_error = ("Task policy rejected", "policy_validation_error")
        except AgentModelNotConfiguredError:
            creation_error = ("Agent model is not configured", "model_not_configured")
        except BudgetCapExceededError as exc:
            scope = "Agent" if exc.agent_id else "Workspace"
            spend = "LLM spend" if exc.kind == "llm" else "spend"
            creation_error = (
                f"{scope} monthly {spend} cap reached ({exc.current_mtd_usd} {exc.currency}/"
                f"{exc.cap_usd} {exc.currency})",
                "monthly_spend_cap_exceeded",
            )
            creation_error_details = {
                "current_mtd_usd": float(exc.current_mtd_usd),
                "cap_usd": float(exc.cap_usd),
                "currency": exc.currency,
                **({"agent_id": exc.agent_id} if exc.agent_id else {}),
            }
        except ValueError:
            logger.error("Agent validation failed for agent %s", agent_id, exc_info=True)
            creation_error = ("Agent validation error", "agent_not_found")
        except Exception:
            logger.error("Task creation failed for agent %s", agent_id, exc_info=True)
            creation_error = ("Task creation failed", "creation_failed")

    if created_task is not None:
        await data.store_webhook_secret(secret_manager, created_task.id)

    async def task_creation_stream() -> AsyncGenerator[str, None]:
        """Generate Server-Sent Events for task creation and execution."""
        task = created_task
        try:
            yield _format_sse_event(
                "connected",
                {
                    "agent_id": str(agent_id),
                    "agent_name": agent.name,
                    "message": "Starting task creation",
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )

            if creation_error is not None:
                error, error_type = creation_error
                error_data: dict[str, str | float | None] = {
                    **({"task_id": None} if error_type == "creation_failed" else {}),
                    "agent_id": str(agent_id),
                    "error": error,
                    "error_type": error_type,
                    **creation_error_details,
                    "timestamp": datetime.now(UTC).isoformat(),
                }
                yield _format_sse_event("error", error_data)
                return
            if task is None:
                raise RuntimeError("Task creation completed without a task")

            yield _format_sse_event(
                "task_created",
                {
                    "task_id": str(task.id),
                    "agent_id": str(agent_id),
                    "description": task.description,
                    "status": task.status,
                    "execution_id": task.execution_id,
                    "created_at": utc_isoformat(task.created_at),
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )

            if task.execution_id and task.status in ["running", "pending"]:
                async for chunk in _tail_task_events_sse(
                    task.id,
                    agent_id,
                    task.execution_id,
                    user_context=user_context,
                    revealed=await caller_may_act_on_task(task, user_context),
                    emit_connected=False,
                    follow_execution=follow,
                ):
                    yield chunk
            else:
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
        except Exception:
            logger.error("Task creation failed for agent %s", agent_id, exc_info=True)
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
        _with_sse_heartbeats(task_creation_stream()),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.post(
    "/sync",
    response_model=TaskResponse,
    dependencies=[
        unrestricted("workspace member; the workspace-scoped repository is the boundary")
    ],
)
async def create_task_for_agent_sync(
    agent_id: UUID,
    data: TaskCreate,
    user_context: UserContextDep,
    secret_manager: BaseSecretManagerDep,
    task_service: TaskService = Depends(get_task_service),
):
    """Create and execute a task for the specified agent (synchronous response)."""
    caller_metadata = data.trusted_metadata(user_context)
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
                trusted_metadata={
                    **caller_metadata,
                    "workspace_attachments": attachment_descriptors,
                },
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
                trusted_metadata=caller_metadata or None,
            )

        await data.store_webhook_secret(secret_manager, task.id)
        # Convert to API response format
        return TaskResponse.from_agent_task(task, user_context)

    except (HTTPException, BudgetCapExceededError):
        raise
    except PolicyValidationError as exc:
        raise HTTPException(status_code=422, detail="Task policy rejected") from exc
    except AgentModelNotConfiguredError as exc:
        raise HTTPException(status_code=422, detail="Agent model is not configured") from exc
    except ValueError as exc:
        # Agent validation errors
        logger.error("Agent validation failed for agent %s", agent_id, exc_info=True)
        raise HTTPException(status_code=404, detail="Agent validation error") from exc
    except Exception as exc:
        logger.error("Task creation failed for agent %s", agent_id, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from exc


class ScheduleTaskCreate(TaskCreate):
    """A task to run once, at a time the caller picks."""

    scheduled_at: datetime

    # Enforced here so a bad time is a 422 on the field, not a generic error
    # raised deeper in when RunCreate re-validates it.
    _validate_scheduled_at = field_validator("scheduled_at")(require_future_instant)


@router.post(
    "/schedule",
    response_model=TaskResponse,
    status_code=201,
    dependencies=[
        unrestricted("workspace member; the workspace-scoped repository is the boundary")
    ],
)
async def schedule_task_for_agent(
    agent_id: UUID,
    data: ScheduleTaskCreate,
    user_context: UserContextDep,
    secret_manager: BaseSecretManagerDep,
    task_service: TaskService = Depends(get_task_service),
):
    """Create a task that runs once at an absolute future time.

    Deliberately not the streaming sibling of ``POST /``: there is nothing to
    stream until the run starts, which may be days away. Repeating schedules
    are cron triggers, not tasks.
    """
    caller_metadata = data.trusted_metadata(user_context)
    try:
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
                scheduled_at=data.scheduled_at,
            )
            task = await task_service.reserve_run(
                payload,
                workspace_id=user_context.workspace_id,
                user_id=user_context.user_id,
                task_id=reserved_task_id,
                trusted_metadata={
                    **caller_metadata,
                    "workspace_attachments": attachment_descriptors,
                },
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
                scheduled_at=data.scheduled_at,
            )
            task = await task_service.start_run(
                payload,
                workspace_id=user_context.workspace_id,
                user_id=user_context.user_id,
                trusted_metadata=caller_metadata or None,
            )

        await data.store_webhook_secret(secret_manager, task.id)
        return TaskResponse.from_agent_task(task, user_context)

    except (HTTPException, BudgetCapExceededError):
        raise
    except SchedulingNotSupportedError as exc:
        raise HTTPException(
            status_code=501,
            detail="This deployment's execution engine cannot defer runs",
        ) from exc
    except PolicyValidationError as exc:
        raise HTTPException(status_code=422, detail="Task policy rejected") from exc
    except AgentModelNotConfiguredError as exc:
        raise HTTPException(status_code=422, detail="Agent model is not configured") from exc
    except ValueError as exc:
        logger.error("Agent validation failed for agent %s", agent_id, exc_info=True)
        raise HTTPException(status_code=404, detail="Agent validation error") from exc
    except Exception as exc:
        logger.error("Task scheduling failed for agent %s", agent_id, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.get(
    "/",
    response_model=list[TaskResponse],
    dependencies=[
        unrestricted("workspace member; the workspace-scoped repository is the boundary")
    ],
)
async def list_agent_tasks(
    agent_id: UUID,
    user_context: UserContextDep,
    status: str | None = Query(None, description="Filter by task status"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of tasks to return"),
    offset: int = Query(0, ge=0, le=MAX_OFFSET, description="Number of tasks to skip"),
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
        # Status and the page are applied in SQL: slicing or filtering after a
        # LIMIT returned an empty page for every offset past the first.
        agent_tasks = await task_service.list_agent_tasks(
            agent_id,
            limit=limit,
            offset=offset,
            status=status.lower() if status else None,
        )

        logger.info(f"Returning {len(agent_tasks)} tasks for agent {agent_id} ({agent.name})")

        return [TaskResponse.from_agent_task(task, user_context) for task in agent_tasks]

    except Exception as e:
        logger.exception(f"Failed to get tasks for agent {agent_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.get(
    "/{task_id}",
    response_model=TaskResponse,
    dependencies=[
        unrestricted("workspace member; the workspace-scoped repository is the boundary")
    ],
)
async def get_agent_task(
    agent_id: UUID,
    task_id: UUID,
    user_context: UserContextDep,
    task_service: TaskService = Depends(get_read_task_service),
):
    """Get a specific task for the specified agent."""
    # No agent-existence gate: the task lookup below already proves the task is
    # in the caller's workspace and belongs to `agent_id`. Requiring the agent
    # to still exist only hid the tasks of deleted agents. See get_task_events.
    try:
        task = await task_service.get_task_with_workflow_status(task_id)
        if task:
            if task.agent_id != agent_id:
                raise HTTPException(status_code=404, detail="Task not found")

            return TaskResponse.from_agent_task(task, user_context)

        # No workflow-status fallback here. task_service.get_task_with_workflow_status
        # is workspace-scoped, so a miss means either "no such task" or "belongs to
        # another workspace" — and reading the Temporal workflow by bare task_id
        # returned that other workspace's result and error to the caller.
        raise HTTPException(status_code=404, detail="Task not found")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.get(
    "/{task_id}/status",
    dependencies=[
        unrestricted("workspace member; the workspace-scoped repository is the boundary")
    ],
)
async def get_agent_task_status(
    agent_id: UUID,
    task_id: UUID,
    user_context: UserContextDep,
    task_service: TaskService = Depends(get_read_task_service),
    workflow_task_service: TemporalWorkflowService = Depends(get_temporal_workflow_service),
):
    """Get the execution status of a specific task workflow."""
    # No agent-existence gate — see get_agent_task.
    try:
        # Persisted business state is enriched only with closed execution outcomes.
        # A live follow-up or human-input waiter must not make the task "running".
        task = await task_service.get_task_with_workflow_status(task_id)
        if not task or str(task.agent_id) != str(agent_id):
            raise HTTPException(status_code=404, detail="Task not found")

        # Get workflow status for live execution detail (timing, session, etc.)
        execution_id = task.execution_id or f"task-{task_id}"
        status = await workflow_task_service.get_workflow_status(execution_id)
        stored_artifacts = await _list_task_artifact_items(
            agent_id=agent_id,
            user_context=user_context,
            task_id=task_id,
        )
        status_artifacts = status.get("artifacts") or []
        if stored_artifacts:
            status_artifacts = [item.model_dump() for item in stored_artifacts]

        # A signal-based pause lives in the workflow's own state; Temporal keeps
        # reporting "running" while the workflow waits, so read it from there.
        execution_status = status.get("execution_status", status.get("status"))
        live_state = (
            await workflow_task_service.get_live_state(execution_id)
            if execution_status == "running"
            else None
        )

        return {
            "task_id": str(task_id),
            "agent_id": str(agent_id),
            "execution_id": execution_id,
            # Authoritative lifecycle status/result come from the persisted task.
            "status": task.status,
            "execution_status": execution_status,
            "paused": bool(live_state and live_state.get("paused")),
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
    created_at: UtcDatetime | None
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
    settings = get_settings()
    secret = settings.sandbox.FILE_SECRET
    if secret is None or not secret.get_secret_value():
        raise HTTPException(status_code=503, detail="Sandbox file access is not configured")
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            return await client.request(
                method,
                f"{settings.mcp.MANAGER_URL.rstrip('/')}{path}",
                params=params,
                headers={"Authorization": f"Bearer {secret.get_secret_value()}"},
            )
    except httpx.RequestError as exc:
        logger.warning("Sandbox manager request failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=503, detail="Sandbox file access is temporarily unavailable"
        ) from exc


async def _sandbox_manager_stream(
    path: str,
    *,
    params: dict[str, str],
) -> tuple[httpx.AsyncClient, httpx.Response]:
    settings = get_settings()
    secret = settings.sandbox.FILE_SECRET
    if secret is None or not secret.get_secret_value():
        raise HTTPException(status_code=503, detail="Sandbox file access is not configured")

    client = httpx.AsyncClient(timeout=300)
    request = client.build_request(
        "GET",
        f"{settings.mcp.MANAGER_URL.rstrip('/')}{path}",
        params=params,
        headers={"Authorization": f"Bearer {secret.get_secret_value()}"},
    )
    try:
        response = await client.send(request, stream=True)
    except httpx.RequestError as exc:
        await client.aclose()
        logger.warning("Sandbox manager streaming request failed: %s", exc, exc_info=True)
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

    content_type = response.headers.get("content-type", default_content_type)
    headers = secure_download_headers(
        content_type=content_type,
        filename=filename,
        disposition=response.headers.get("content-disposition"),
        fallback="artifact.bin",
    )
    if content_length := response.headers.get("content-length"):
        headers["Content-Length"] = content_length
    return StreamingResponse(
        stream_content(),
        media_type=content_type,
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
    user_context: UserContext,
    task_id: UUID,
) -> list[TaskArtifactItem]:
    response = await _sandbox_manager_request(
        "GET",
        "/sandbox/artifacts",
        params={"workspace_id": user_context.workspace_id, "task_id": str(task_id)},
    )
    _raise_sandbox_manager_error(response, resource="Artifact list")
    try:
        result = _ManagerArtifactList.model_validate(response.json())
    except (ValueError, ValidationError) as exc:
        logger.exception("Sandbox manager returned an invalid artifact list: %s", exc)
        raise HTTPException(status_code=502, detail="Artifact list response is invalid") from exc
    prefix = await workspace_api_prefix(user_context)
    return [
        TaskArtifactItem(
            id=item.id,
            path=item.path,
            name=item.name,
            size=item.size,
            content_type=item.content_type or None,
            sha256=item.sha256 or None,
            created_at=item.created_at,
            download_url=_task_artifact_download_url(prefix, agent_id, task_id, item.id),
        )
        for item in result.items
    ]


def _task_artifact_download_url(
    workspace_prefix: str, agent_id: UUID, task_id: UUID, artifact_id: str
) -> str:
    return f"{workspace_prefix}/agents/{agent_id}/tasks/{task_id}/artifacts/files/{artifact_id}"


async def _verify_task_for_agent(task_service: TaskService, agent_id: UUID, task_id: UUID) -> Any:
    task = await task_service.get_task(task_id)
    if not task or str(task.agent_id) != str(agent_id):
        raise HTTPException(status_code=404, detail="Task not found")
    return task


def task_execution_id(task: Any) -> str:
    """The workflow of a task's run: the one its row records, else the one its start uses.

    A delegated child runs under its parent's id for it, never ``task-<id>``.
    """
    return task.execution_id or f"task-{task.id}"


@router.get(
    "/{task_id}/artifacts",
    response_model=list[TaskArtifactItem],
    dependencies=[
        unrestricted("workspace member; the workspace-scoped repository is the boundary")
    ],
)
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
        user_context=user_context,
        task_id=task_id,
    )


@router.get(
    "/{task_id}/artifacts/files/{artifact_path:path}",
    dependencies=[
        unrestricted("workspace member; the workspace-scoped repository is the boundary")
    ],
)
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


@router.get(
    "/{task_id}/sandbox/files",
    response_model=SandboxFileListResponse,
    dependencies=[
        unrestricted("workspace member; the workspace-scoped repository is the boundary")
    ],
)
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
        logger.exception("Sandbox manager returned an invalid file list: %s", exc)
        raise HTTPException(status_code=502, detail="Sandbox file list is invalid") from exc
    items = [SandboxFileItem(path=path) for path in result.paths]
    return SandboxFileListResponse(items=items, total=len(items))


@router.get(
    "/{task_id}/sandbox/files/{file_path:path}",
    dependencies=[
        unrestricted("workspace member; the workspace-scoped repository is the boundary")
    ],
)
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
    """Headline rollup for a single task: its run times, answer, error and spend.

    Read from the task row and the spend ledger. ``cost`` sums the task's current
    ledger lines in ``currency``, the billing currency. ``duration_ms`` runs from the
    task's first start to its last end, idle waits between turns included.
    """

    task_id: UUID
    agent_id: UUID
    workspace_id: str
    status: str
    started_at: UtcDatetime | None = None
    ended_at: UtcDatetime | None = None
    duration_ms: float | None = None
    cost: float = 0.0
    currency: str
    final_response: str | None = None
    last_error: str | None = None


@router.get(
    "/{task_id}/summary",
    response_model=TaskSummary,
    dependencies=[
        unrestricted("workspace member; the workspace-scoped repository is the boundary")
    ],
)
async def get_task_summary(
    agent_id: UUID,
    task_id: UUID,
    user_context: UserContextDep,
    repository_factory: ReadRepositoryFactoryDep,
) -> TaskSummary:
    """Per-task rollup from the task row and the spend ledger.

    Workspace-scoped: the task must belong to the caller's workspace and
    the agent must match, or we return 404 (same shape as other task
    endpoints — no information leak).
    """
    tasks = repository_factory.create_repository(TaskRepository)
    task = await tasks.get_task(task_id)
    if task is None or task.agent_id != agent_id:
        raise HTTPException(status_code=404, detail="Task not found")

    ended_at = task.completed_at if task.status in ENDED_TASK_STATUSES else None
    response = task.result.get("response") if isinstance(task.result, dict) else None
    return TaskSummary(
        task_id=task.id,
        agent_id=task.agent_id,
        workspace_id=user_context.workspace_id,
        status=task.status,
        started_at=task.started_at,
        ended_at=ended_at,
        duration_ms=(ended_at - task.started_at).total_seconds() * 1000
        if ended_at and task.started_at
        else None,
        cost=float(await tasks.sum_task_spend(task.id)),
        currency=get_customer_pricing().currency(),
        final_response=response if isinstance(response, str) else None,
        last_error=task.error,
    )


# Ended for good. A completed task can still have a workflow waiting for a
# follow-up, which a cancel ends.
_ENDED_UNCANCELLABLE_STATUSES = frozenset({"failed", "blocked", "cancelled"})


@router.delete(
    "/{task_id}",
    dependencies=[requires_task_authority()],
)
async def cancel_agent_task(
    agent_id: UUID,
    task_id: UUID,
    user_context: UserContextDep,
    agent_service: AgentService = Depends(get_agent_service),
    task_service: TaskService = Depends(get_task_service),
    workflow_task_service: TemporalWorkflowService = Depends(get_temporal_workflow_service),
):
    """Cancel a specific task workflow for the specified agent."""
    # Verify agent exists
    agent = await agent_service.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    # The Temporal handle below is addressed by bare task_id, so owning any agent
    # would otherwise be enough to act on any workspace's task.
    task = await _verify_task_for_agent(task_service, agent_id, task_id)
    # A run that already ended has nothing to cancel; saying "cancelled" would
    # contradict the status it keeps.
    if task.status in _ENDED_UNCANCELLABLE_STATUSES:
        raise HTTPException(status_code=409, detail=f"Task already ended: {task.status}")

    try:
        execution_id = task_execution_id(task)
        # A run booked for later has not started, so no workflow code will ever
        # record the cancellation: the task manager cancels and records it. A
        # started run records its own cancellation.
        if task.status == "scheduled":
            success = await task_service.cancel_task(task_id)
        else:
            success = await workflow_task_service.cancel_task(execution_id)

        if success:
            return {"status": "cancelled", "task_id": str(task_id), "execution_id": execution_id}
        else:
            raise HTTPException(status_code=404, detail="Task not found or already completed")

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to cancel task %s", task_id, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from e


# Workflow states no signal can reach any more: pausing, resuming or answering
# one is a 400, not a signal that fails inside Temporal. "terminated" is what
# the executor reports for a workflow killed from outside it.
_FINISHED_WORKFLOW_STATES = frozenset(
    status.value
    for status in (
        WorkflowStatus.COMPLETED,
        WorkflowStatus.FAILED,
        WorkflowStatus.CANCELLED,
        WorkflowStatus.TERMINATED,
    )
)


@router.post(
    "/{task_id}/pause",
    dependencies=[requires_task_authority()],
)
async def pause_agent_task(
    agent_id: UUID,
    task_id: UUID,
    user_context: UserContextDep,
    agent_service: AgentService = Depends(get_agent_service),
    task_service: TaskService = Depends(get_task_service),
    workflow_task_service: TemporalWorkflowService = Depends(get_temporal_workflow_service),
):
    """Pause a specific task workflow for the specified agent."""
    # Verify agent exists
    agent = await agent_service.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    task = await _verify_task_for_agent(task_service, agent_id, task_id)

    try:
        # Get current task status to validate it can be paused
        execution_id = task_execution_id(task)
        status = await workflow_task_service.get_workflow_status(execution_id)

        # Check if task exists
        if status.get("status") == "unknown":
            raise HTTPException(status_code=404, detail="Task not found")

        # Check if task is in a pausable state
        current_status = status.get("status", "").lower()
        if current_status in _FINISHED_WORKFLOW_STATES:
            raise HTTPException(
                status_code=400, detail=f"Cannot pause task in '{current_status}' state"
            )

        # A pause is a signal the workflow holds in its own state; Temporal's
        # execution status stays "running" while it waits.
        live_state = await workflow_task_service.get_live_state(execution_id)
        if live_state and live_state.get("paused"):
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
        logger.exception(f"Failed to pause task {task_id} for agent {agent_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.post(
    "/{task_id}/resume",
    dependencies=[requires_task_authority()],
)
async def resume_agent_task(
    agent_id: UUID,
    task_id: UUID,
    user_context: UserContextDep,
    agent_service: AgentService = Depends(get_agent_service),
    task_service: TaskService = Depends(get_task_service),
    workflow_task_service: TemporalWorkflowService = Depends(get_temporal_workflow_service),
):
    """Resume a paused task workflow for the specified agent."""
    # Verify agent exists
    agent = await agent_service.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    task = await _verify_task_for_agent(task_service, agent_id, task_id)

    try:
        # Get current task status to validate it can be resumed
        execution_id = task_execution_id(task)
        status = await workflow_task_service.get_workflow_status(execution_id)

        # Check if task exists
        if status.get("status") == "unknown":
            raise HTTPException(status_code=404, detail="Task not found")

        # Reject only terminal states. Signal-based pause does NOT flip
        # Temporal's external status to "paused" (the workflow keeps the
        # "running" execution status while its internal handler waits on
        # the pause flag), so gating on "paused/blocked" here would 400
        # every legitimate resume right after a pause. The workflow's own
        # state says whether it is paused.
        current_status = status.get("status", "").lower()
        if current_status in _FINISHED_WORKFLOW_STATES:
            raise HTTPException(
                status_code=400, detail=f"Cannot resume task in '{current_status}' state"
            )

        live_state = await workflow_task_service.get_live_state(execution_id)
        if live_state is not None and not live_state.get("paused"):
            raise HTTPException(status_code=400, detail="Task is not paused")

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
        logger.exception(f"Failed to resume task {task_id} for agent {agent_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error") from e


_RUN_STILL_CLOSING = (
    "The task is still stopping: it is recording the call it interrupted. "
    "Send this again in a few seconds."
)


@router.post(
    "/{task_id}/retry",
    dependencies=[requires_task_authority()],
)
async def retry_agent_task(
    agent_id: UUID,
    task_id: UUID,
    user_context: UserContextDep,
    agent_service: AgentService = Depends(get_agent_service),
    task_service: TaskService = Depends(get_task_service),
):
    """Re-run the turn a failed task ended on, on the same conversation.

    A new run of the task continues its conversation with no new message, so
    the model is called again on the input that failed; the run records a
    ``task.retried`` event.
    """
    agent = await agent_service.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    await _verify_task_for_agent(task_service, agent_id, task_id)

    try:
        retried = await task_service.retry_last_turn(task_id)
    except RunStillClosingError as exc:
        raise HTTPException(status_code=409, detail=_RUN_STILL_CLOSING) from exc
    except BudgetCapExceededError:
        raise
    except PolicyValidationError as exc:
        raise HTTPException(status_code=422, detail="Task policy rejected") from exc
    except Exception as e:
        logger.exception(f"Failed to retry task {task_id} for agent {agent_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error") from e
    if not retried:
        raise HTTPException(
            status_code=409,
            detail="Only a failed task whose run has finished can be retried.",
        )
    return {"status": "running", "task_id": str(task_id), "execution_id": f"task-{task_id}"}


@router.post(
    "/{task_id}/a2ui/action",
    dependencies=[requires_task_authority()],
)
async def send_a2ui_action(
    agent_id: UUID,
    task_id: UUID,
    action: A2UIActionPayload,
    user_context: UserContextDep,
    agent_service: AgentService = Depends(get_agent_service),
    task_service: TaskService = Depends(get_task_service),
    workflow_task_service: TemporalWorkflowService = Depends(get_temporal_workflow_service),
):
    """Send an A2UI user action to a running task workflow."""
    agent = await agent_service.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    if not getattr(agent, "a2ui_enabled", False):
        raise HTTPException(status_code=400, detail="Agent does not have A2UI enabled")

    task = await _verify_task_for_agent(task_service, agent_id, task_id)

    try:
        execution_id = task_execution_id(task)
        status = await workflow_task_service.get_workflow_status(execution_id)
        current_status = status.get("execution_status", status.get("status", "")).lower()

        if current_status == "unknown":
            raise HTTPException(status_code=404, detail="Task not found")

        if current_status != "running":
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
        logger.exception(f"Failed to send A2UI action for task {task_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.post(
    "/{task_id}/input",
    dependencies=[requires_task_authority()],
)
async def submit_task_input(
    agent_id: UUID,
    task_id: UUID,
    submission: TaskInputSubmission,
    user_context: UserContextDep,
    secret_manager: BaseSecretManagerDep,
    agent_service: AgentService = Depends(get_agent_service),
    task_service: TaskService = Depends(get_task_service),
    workflow_task_service: TemporalWorkflowService = Depends(get_temporal_workflow_service),
):
    """Submit structured user input to a workflow waiting on request_user_input.

    Secret values are written to the workspace secret manager at the API boundary.
    Only secret refs are sent to Temporal/LLM context.
    """
    task = await _verify_task_for_agent(task_service, agent_id, task_id)

    agent = await agent_service.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    execution_id = task_execution_id(task)

    try:
        status = await workflow_task_service.get_workflow_status(execution_id)
        if status.get("status") == "unknown":
            raise HTTPException(status_code=404, detail="Task not found")

        current_status = status.get("status", "").lower()
        if current_status in _FINISHED_WORKFLOW_STATES:
            raise HTTPException(
                status_code=400, detail=f"Cannot submit input to task in '{current_status}' state"
            )

        secret_refs: dict[str, dict[str, str]] = {}
        for field_name, raw_secret in submission.secrets.items():
            if isinstance(raw_secret, InputSecretValue) and raw_secret.secret_name:
                # set_secret upserts on (workspace_id, name), so a caller-chosen
                # name that lands on a platform prefix either overwrites the
                # credential a connection resolves, or mints a row that renders
                # on the secrets page as a connection's credential which does
                # not exist. Only the prefixes are refused: the slug shape that
                # POST /v1/secrets enforces is a house style for names it
                # creates, and applying it here would break namespaced input
                # names like `service/api_token` that already work.
                if has_reserved_prefix(raw_secret.secret_name):
                    raise HTTPException(
                        status_code=422,
                        detail=(
                            f"Secret name '{raw_secret.secret_name}' uses a prefix reserved "
                            "for secrets the platform manages on behalf of a connection."
                        ),
                    )
                secret_value = raw_secret.value
                secret_name = raw_secret.secret_name
            elif isinstance(raw_secret, InputSecretValue):
                secret_value = raw_secret.value
                secret_name = _default_input_secret_name(task_id, field_name)
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
    if model_spec.kind != ModelKind.CHAT:
        raise HTTPException(
            status_code=409,
            detail=f"Model instance is a {model_spec.kind} model; a task runs on a chat model",
        )

    return {
        "model_id": str(instance.id),
        "provider_type": provider_spec.provider_type,
        "model_name": model_spec.model_name,
        "api_key_secret": provider_config.api_key,
        # Whose credentials the rest of the run will spend. Switching model switches
        # this too, and omitting it here would have defaulted every switched-to model
        # to "the customer's own key" — including a platform one, whose calls we pay
        # for and whose entitlement check would then quietly go back to failing open.
        "managed_by": provider_config.managed_by,
        "endpoint_url": provider_config.endpoint_url,
        "context_window": model_spec.context_window,
        "max_output_tokens": model_spec.max_output_tokens,
        "input_cost_per_token": model_spec.input_cost_per_token,
        "output_cost_per_token": model_spec.output_cost_per_token,
        "cached_input_cost_per_token": model_spec.cached_input_cost_per_token,
        "cache_creation_input_cost_per_token": model_spec.cache_creation_input_cost_per_token,
        "display_name": model_spec.display_name,
        "provider_display_name": provider_spec.name,
        "supports_vision": model_spec.supports_vision,
        "resolved_at": datetime.now(UTC).isoformat(),
    }


@router.post(
    "/{task_id}/command",
    dependencies=[requires_task_authority()],
)
async def send_task_command(
    agent_id: UUID,
    task_id: UUID,
    payload: TaskCommandPayload,
    user_context: UserContextDep,
    agent_service: AgentService = Depends(get_agent_service),
    task_service: TaskService = Depends(get_task_service),
    workflow_task_service: TemporalWorkflowService = Depends(get_temporal_workflow_service),
    model_instance_service: ModelInstanceService = Depends(get_model_instance_service),
):
    """Send a command to a running task workflow."""
    # Verify agent exists
    agent = await agent_service.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    task = await _verify_task_for_agent(task_service, agent_id, task_id)

    execution_id = task_execution_id(task)

    try:
        if payload.command == "change_model":
            if not payload.model_instance_id:
                raise HTTPException(
                    status_code=400, detail="model_instance_id is required for change_model"
                )
            resolved = await _resolve_model_info(payload.model_instance_id, model_instance_service)
            delivered = await workflow_task_service.send_workflow_command(
                execution_id, "change_model", {**resolved, "changed_by": user_context.user_id}
            )

        elif payload.command == "queue_message":
            if not payload.message:
                raise HTTPException(status_code=400, detail="message is required for queue_message")
            # A completed, stopped or failed task whose workflow has closed
            # continues in a new run.
            delivered = await task_service.queue_follow_up(task_id, payload.message)

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

    except (HTTPException, BudgetCapExceededError):
        raise
    except RunStillClosingError as exc:
        raise HTTPException(status_code=409, detail=_RUN_STILL_CLOSING) from exc
    except PolicyValidationError as exc:
        raise HTTPException(status_code=422, detail="Task policy rejected") from exc
    except Exception as e:
        logger.error(
            f"Failed to send command '{payload.command}' for task {task_id}: {e}", exc_info=True
        )
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.post(
    "/{task_id}/resolve-escalation",
    dependencies=[
        enforced_in_handler(
            "an escalation's named approvers, else whoever may act on the run; "
            "checked in the handler against the workflow's pending escalation"
        )
    ],
)
async def resolve_task_escalation(
    agent_id: UUID,
    task_id: UUID,
    data: EscalationResolution,
    user_context: UserContextDep,
    agent_service: AgentService = Depends(get_agent_service),
    task_service: TaskService = Depends(get_task_service),
    workflow_task_service: TemporalWorkflowService = Depends(get_temporal_workflow_service),
):
    """Resolve a tool escalation for the specified task workflow."""
    # Verify agent exists
    agent = await agent_service.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    task = await _verify_task_for_agent(task_service, agent_id, task_id)
    execution_id = task_execution_id(task)
    if not await caller_may_act_on_task(task, user_context):
        try:
            pending = await workflow_task_service.get_pending_escalations(execution_id)
        except WorkflowNotFoundError as e:
            raise HTTPException(
                status_code=404, detail="Escalation not found or no longer pending"
            ) from e
        escalation = next((e for e in pending if e["escalation_id"] == data.escalation_id), None)
        if escalation is None:
            raise HTTPException(status_code=404, detail="Escalation not found or no longer pending")
        if not may_resolve_escalation(
            escalation["approvers"], str(user_context.user_id), may_act_on_run=False
        ):
            raise HTTPException(
                status_code=403, detail="You are not an approver of this escalation"
            )

    try:
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
    except EscalationNotPendingError as e:
        raise HTTPException(
            status_code=404, detail="Escalation not found or no longer pending"
        ) from e
    except NotAnApproverError as e:
        raise HTTPException(
            status_code=403, detail="You are not an approver of this escalation"
        ) from e
    except Exception as e:
        logger.error(
            "Failed to resolve escalation for task %s, agent %s", task_id, agent_id, exc_info=True
        )
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.get(
    "/{task_id}/events",
    response_model=TaskEventResponse,
    dependencies=[
        unrestricted("workspace member; the workspace-scoped repository is the boundary")
    ],
)
async def get_task_events(
    agent_id: UUID,
    task_id: UUID,
    repository_factory: ReadRepositoryFactoryDep,
    page: int = Query(1, ge=1, le=MAX_PAGE, description="Page number"),
    page_size: int = Query(50, ge=1, le=100, description="Number of events per page"),
    event_type: str | None = Query(None, description="Filter by event type"),
    task_service: TaskService = Depends(get_read_task_service),
):
    """One page of the task's feed from its log: event rows and the messages a person sent."""
    # Gate on the task, not the agent. Requiring `agent_id` to still resolve
    # gated a task's history on its agent existing — deleting an agent silently
    # took the Events tab of every task it ever ran down with it. The workspace
    # filter inside the repositories is the actual authorization boundary; the
    # ownership check matches the sibling task endpoints and keeps the caller
    # from stamping an arbitrary `agent_id` onto this task's events below.
    task = await task_service.get_task(task_id)
    if not task or str(task.agent_id) != str(agent_id):
        raise HTTPException(status_code=404, detail="Task not found")

    try:
        reader = TaskFeedReader(repository_factory.session, repository_factory.user_context)
        entries, total_events = await reader.page(
            task_id,
            event_type=event_type,
            limit=page_size,
            offset=(page - 1) * page_size,
        )
        shows_tools = any(entry.name in (TOOL_CALL, TOOL_RESULT) for entry in entries)
        bodies = await reader.bodies(
            task_id,
            entries,
            revealed=shows_tools
            and await caller_may_act_on_task(task, repository_factory.user_context),
        )

        events = []
        for entry in entries:
            shown = feed_event(entry, bodies)
            if shown is None:
                continue
            shown_type, data = shown
            if entry.occurred_at is None:
                raise RuntimeError(f"task {task_id} log row {entry.seq} was read without its time")
            events.append(
                TaskEvent(
                    id=str(entry.event_id),
                    task_id=str(task_id),
                    agent_id=str(agent_id),
                    execution_id=entry.execution_id or data.get("execution_id"),
                    timestamp=entry.occurred_at,
                    event_type=shown_type,
                    message=data.get("message"),
                    event_id=str(entry.event_id),
                    seq=entry.seq,
                    data=_filter_domain_fields(dict(data)),
                    metadata=dict(data),
                )
            )

        return TaskEventResponse(
            events=events,
            total=total_events,
            page=page,
            page_size=page_size,
            has_next=(page * page_size) < total_events,
        )

    except Exception as e:
        logger.exception(f"Failed to get task events for task {task_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error") from e


class PendingEscalationResponse(BaseModel):
    escalation_id: str
    tool_name: str
    tool_call_id: str
    tool_args: dict[str, Any]


def escalations_caller_may_resolve(
    pending: list[dict[str, Any]], user_id: str, *, may_act_on_run: bool
) -> list[PendingEscalationResponse]:
    """The pending escalations this caller may decide, with their arguments."""
    return [
        PendingEscalationResponse(
            escalation_id=escalation["escalation_id"],
            tool_name=escalation["tool_name"],
            tool_call_id=escalation["tool_call_id"],
            tool_args=escalation["tool_args"],
        )
        for escalation in pending
        if may_resolve_escalation(escalation["approvers"], user_id, may_act_on_run=may_act_on_run)
    ]


@router.get(
    "/{task_id}/escalations",
    response_model=list[PendingEscalationResponse],
    dependencies=[
        enforced_in_handler(
            "an escalation's named approvers, else whoever may act on the run; "
            "the handler shows each caller only the escalations they may decide"
        )
    ],
)
async def list_pending_escalations(
    agent_id: UUID,
    task_id: UUID,
    user_context: UserContextDep,
    task_service: TaskService = Depends(get_task_service),
    workflow_task_service: TemporalWorkflowService = Depends(get_temporal_workflow_service),
) -> list[PendingEscalationResponse]:
    """The escalations awaiting this caller's decision, with the exact arguments.

    The event log redacts tool arguments, since a command can carry an inline
    secret; the caller reads them here only where they may resolve the escalation.
    """
    task = await _verify_task_for_agent(task_service, agent_id, task_id)
    may_act = await caller_may_act_on_task(task, user_context)
    try:
        pending = await workflow_task_service.get_pending_escalations(task_execution_id(task))
    except WorkflowNotFoundError as e:
        raise HTTPException(status_code=404, detail="Task has no workflow") from e
    shown = escalations_caller_may_resolve(
        pending, str(user_context.user_id), may_act_on_run=may_act
    )
    if not may_act and not shown:
        raise HTTPException(status_code=403, detail="You may not act on this task")
    return shown


@router.get(
    "/{task_id}/events/stream",
    dependencies=[
        unrestricted("workspace member; the workspace-scoped repository is the boundary")
    ],
)
async def stream_task_events(
    agent_id: UUID,
    task_id: UUID,
    request: Request,
    user_context: UserContextDep,
    include_chunks: bool = Query(
        True, description="Include incremental llm.call.chunk token events in the stream"
    ),
    task_service: TaskService = Depends(get_read_task_service),
):
    """Stream real-time task execution events via Server-Sent Events."""
    try:
        # Gated on the task, not the agent — see get_task_events. An agent that
        # no longer resolves must not take the live stream of its past tasks
        # down with it, but `agent_id` still has to own the task: it is echoed
        # into every frame this stream emits.
        task = await task_service.get_task(task_id)
        if not task or str(task.agent_id) != str(agent_id):
            raise HTTPException(status_code=404, detail="Task not found")
        revealed = await caller_may_act_on_task(task, user_context)

        # Create SSE stream by tailing the task_events table (single source of
        # truth, no pub/sub race) via the shared helper.
        async def event_stream() -> AsyncGenerator[str, None]:
            try:
                async for chunk in _tail_task_events_sse(
                    task_id,
                    agent_id,
                    task.execution_id,
                    user_context=user_context,
                    revealed=revealed,
                    include_chunks=include_chunks,
                    last_event_id=request.headers.get("last-event-id"),
                ):
                    yield chunk

            except Exception as e:
                logger.exception(f"Fatal error in SSE stream for task {task_id}: {e}")
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
            _with_sse_heartbeats(event_stream()),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to create SSE stream for task {task_id}: {e}")
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


def _format_sse_event(event_type: str, data: dict[str, Any], event_id: str | None = None) -> str:
    """Format data as Server-Sent Event."""
    import json

    event_data = json.dumps(data)
    id_line = f"id: {event_id}\n" if event_id else ""
    return f"{id_line}event: {event_type}\ndata: {event_data}\n\n"
