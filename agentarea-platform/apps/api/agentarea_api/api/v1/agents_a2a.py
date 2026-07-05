"""A2A (Agent-to-Agent) protocol endpoints for AgentArea.

This module implements the A2A protocol for inter-agent communication.
The A2A protocol is a JSON-RPC based protocol that allows agents to:
- Send messages to other agents
- Submit tasks for execution
- Query task status
- Cancel tasks

Key endpoints:
- POST /agents/{agent_id}/a2a/rpc - JSON-RPC endpoint for A2A protocol
- GET /agents/{agent_id}/a2a/.well-known - Agent discovery endpoint
"""

import json
import logging
import time
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from agentarea_agents.application.agent_service import AgentService
from agentarea_api.api.deps.services import (
    get_agent_service,
    get_secret_manager,
    get_task_service,
)
from agentarea_api.api.v1.a2a_auth import (
    A2AAuthContext,
    allow_public_access,
    require_a2a_execute_auth,
)
from agentarea_api.api.v1.task_event_feed import open_task_event_feed
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.context_manager import ContextManager
from agentarea_common.infrastructure.secret_manager import BaseSecretManager
from agentarea_common.utils.a2a_push import (
    delete_push_config,
    get_push_config,
    list_push_configs,
    push_token_secret_name,
    task_push_config_result,
    upsert_push_config,
)
from agentarea_common.utils.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
    Artifact,
    CancelTaskResponse,
    GetTaskResponse,
    JSONRPCError,
    JSONRPCRequest,
    JSONRPCResponse,
    Message,
    MessageSendParams,
    StreamResponseArtifactUpdate,
    StreamResponseStatusUpdate,
    StreamResponseTask,
    Task,
    TaskState,
    TaskStatus,
    TextPart,
)
from agentarea_common.utils.types import (
    GetExtendedAgentCardResponse as AgentAuthenticatedExtendedCardResponse,
)
from agentarea_common.utils.types import (
    MessageSendResponse as SendMessageResponse,
)
from agentarea_common.utils.url_safety import UnsafeUrlError, validate_outbound_url
from agentarea_tasks.domain.models import AgentTask, TaskUpdate
from agentarea_tasks.task_service import TaskService
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import ValidationError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/a2a")


def log_a2a_operation(
    operation: str,
    agent_id: UUID,
    auth_context: A2AAuthContext,
    request_id: str | int | None = None,
    task_id: UUID | None = None,
    status: str = "started",
    duration_ms: float | None = None,
    error: str | None = None,
    extra_metadata: dict[str, Any] | None = None,
) -> None:
    """Log A2A operations with structured metadata for monitoring and debugging.

    Args:
        operation: The A2A operation being performed (e.g., "task_send", "message_stream")
        agent_id: The target agent ID
        auth_context: A2A authentication context
        request_id: JSON-RPC request ID
        task_id: Task ID if applicable
        status: Operation status (started, completed, failed)
        duration_ms: Operation duration in milliseconds
        error: Error message if operation failed
        extra_metadata: Additional metadata to include in logs
    """
    # Build structured log data
    log_data = {
        "a2a_operation": operation,
        "agent_id": str(agent_id),
        "request_id": request_id,
        "status": status,
        "auth_method": auth_context.auth_method,
        "authenticated": auth_context.authenticated,
        "user_id": auth_context.user_id,
        "workspace_id": auth_context.workspace_id,
        "permissions": auth_context.permissions,
        "timestamp": datetime.now(UTC).isoformat(),
    }

    # Add task ID if provided
    if task_id:
        log_data["task_id"] = str(task_id)

    # Add duration if provided
    if duration_ms is not None:
        log_data["duration_ms"] = duration_ms

    # Add error if provided
    if error:
        log_data["error"] = error

    # Add client metadata from auth context
    if auth_context.metadata:
        client_metadata = {}
        for key in ["user_agent", "client_ip", "forwarded_for"]:
            if auth_context.metadata.get(key):
                client_metadata[key] = auth_context.metadata[key]
        if client_metadata:
            log_data["client_metadata"] = client_metadata

    # Add extra metadata
    if extra_metadata:
        log_data.update(extra_metadata)

    # Log at appropriate level based on status
    if status == "failed" or error:
        logger.error(f"A2A {operation} failed", extra={"a2a_metrics": log_data})
    elif status == "completed":
        logger.info(f"A2A {operation} completed", extra={"a2a_metrics": log_data})
    else:
        logger.info(f"A2A {operation} {status}", extra={"a2a_metrics": log_data})


def set_user_context_from_a2a_auth(auth_context: A2AAuthContext) -> None:
    """Convert A2A authentication context to UserContext and set it in ContextManager.

    This ensures that the repository layer has access to the proper user context
    for workspace scoping and audit fields (created_by, workspace_id).

    Args:
        auth_context: A2A authentication context from the request

    Raises:
        ValueError: If authentication context is missing required user_id or workspace_id
    """
    # Require authentication for A2A requests
    if not auth_context.authenticated or not auth_context.user_id:
        raise ValueError(
            "A2A requests require authentication. Unauthenticated requests are not supported."
        )

    if not auth_context.workspace_id:
        raise ValueError(
            f"A2A request missing workspace_id for authenticated user {auth_context.user_id}"
        )

    # Create UserContext for repository layer
    user_context = UserContext(
        user_id=auth_context.user_id,
        workspace_id=auth_context.workspace_id,
    )

    # Set context in ContextManager so repositories can access it
    ContextManager.set_context(user_context)

    logger.debug(
        f"Set user context for A2A request: user_id={auth_context.user_id}, "
        f"workspace_id={auth_context.workspace_id}"
    )


class A2AValidationError(Exception):
    """Custom exception for A2A validation errors."""

    def __init__(self, message: str, code: int = -32602):
        self.message = message
        self.code = code
        super().__init__(message)


class A2ATaskServiceError(Exception):
    """Custom exception for A2A task service errors."""

    def __init__(self, message: str, code: int = -32603):
        self.message = message
        self.code = code
        super().__init__(message)


def create_error_response(
    request_id: str | int | None, error_code: int, error_message: str, error_data: Any = None
) -> JSONRPCResponse:
    """Create a standardized JSON-RPC error response."""
    return JSONRPCResponse(
        jsonrpc="2.0",
        id=request_id,
        error=JSONRPCError(code=error_code, message=error_message, data=error_data),
    )


async def validate_agent_exists(agent_service: AgentService, agent_id: UUID) -> None:
    """Validate that an agent exists and is available before processing requests.

    Args:
        agent_service: The agent service to use for validation
        agent_id: The agent ID to validate

    Raises:
        A2AValidationError: If agent doesn't exist or is not available
    """
    try:
        agent = await agent_service.get(agent_id)
        if not agent:
            raise A2AValidationError(f"Agent with ID {agent_id} does not exist", -32602)

        # Check if agent is in an available status
        if agent.status and agent.status.lower() not in ["active", "available", "ready"]:
            raise A2AValidationError(
                f"Agent {agent.name} (ID: {agent_id}) is not available (status: {agent.status})",
                -32602,
            )

    except A2AValidationError:
        # Re-raise validation errors as-is
        raise
    except Exception as e:
        logger.error(f"Error validating agent existence for {agent_id}: {e}")
        raise A2AValidationError(f"Failed to validate agent availability: {e}", -32603) from None


def validate_message_send_params(params: dict[str, Any]) -> MessageSendParams:
    """Validate and parse MessageSendParams.

    Args:
        params: Raw parameters from JSON-RPC request

    Returns:
        Validated MessageSendParams object

    Raises:
        A2AValidationError: If validation fails
    """
    try:
        return MessageSendParams(**params)
    except ValidationError as e:
        error_details = []
        for error in e.errors():
            field = ".".join(str(x) for x in error["loc"])
            error_details.append(f"{field}: {error['msg']}")
        raise A2AValidationError(
            f"Invalid message parameters: {'; '.join(error_details)}", -32602
        ) from None
    except Exception as e:
        raise A2AValidationError(f"Failed to parse message parameters: {e}", -32602) from None


def validate_task_id_param(params: dict[str, Any]) -> UUID:
    """Validate and parse task ID parameter.

    Args:
        params: Raw parameters from JSON-RPC request

    Returns:
        Validated UUID

    Raises:
        A2AValidationError: If validation fails
    """
    task_id_str = params.get("id")
    if not task_id_str:
        raise A2AValidationError("Missing required parameter: id", -32602)

    try:
        return UUID(task_id_str)
    except ValueError as e:
        raise A2AValidationError(f"Invalid task ID format: {task_id_str}", -32602) from e


def _extract_text_from_parts(parts):
    return "".join(
        part.get("text", "") for part in parts if isinstance(part, dict) and "text" in part
    )


def convert_a2a_message_to_task(
    message_params: MessageSendParams,
    agent_id: UUID,
    auth_context: A2AAuthContext,
    a2a_method: str,
    request_id: str,
    task_id: str | None = None,
) -> AgentTask:
    """Convert A2A message to AgentTask with proper authentication context and user metadata."""
    message_content = ""
    if message_params.message and message_params.message.parts:
        for part in message_params.message.parts:
            if part.text:
                message_content += part.text

    # Extract proper user context from authentication
    # Note: The user context should already be set in ContextManager by
    # set_user_context_from_a2a_auth()
    if not auth_context.authenticated or not auth_context.user_id:
        raise A2AValidationError("Authentication required for task submission", -32600)

    if not auth_context.workspace_id:
        raise A2AValidationError(
            f"Missing workspace_id in authentication context for user {auth_context.user_id}",
            -32600,
        )

    user_id = auth_context.user_id
    workspace_id = auth_context.workspace_id

    # Create comprehensive A2A metadata with security context and monitoring information
    a2a_metadata = {
        "source": "a2a",
        "a2a_method": a2a_method,
        "a2a_request_id": request_id,
        "auth_method": auth_context.auth_method,
        "authenticated": auth_context.authenticated,
        "created_via": "a2a_protocol",
        "created_timestamp": datetime.now(UTC).isoformat(),
        "security_context": {
            "user_id": user_id,
            "workspace_id": workspace_id,
            "permissions": auth_context.permissions,
            "auth_timestamp": datetime.now(UTC).isoformat(),
        },
        # Monitoring and analytics metadata
        "monitoring": {
            "task_source": "a2a_protocol",
            "protocol_version": "1.0",
            "message_length": len(message_content) if message_content else 0,
            "has_message_parts": bool(message_params.message and message_params.message.parts),
            "message_parts_count": len(message_params.message.parts)
            if message_params.message and message_params.message.parts
            else 0,
            "is_streaming": a2a_method == "SendStreamingMessage",
            "agent_target": str(agent_id),
        },
    }
    # Merge any provided metadata from A2A params (e.g., requires_human_approval)
    extra_metadata = getattr(message_params, "metadata", None)
    if extra_metadata:
        try:
            a2a_metadata.update(extra_metadata)
        except Exception:  # noqa: S110
            # If metadata merging fails, continue with base metadata
            pass

    # Add agent info if available in auth context
    if "agent_name" in auth_context.metadata:
        a2a_metadata["target_agent_name"] = auth_context.metadata["agent_name"]

    # Add client metadata for audit trail
    if auth_context.metadata:
        client_metadata = {}
        for key in ["user_agent", "client_ip", "forwarded_for"]:
            if auth_context.metadata.get(key):
                client_metadata[key] = auth_context.metadata[key]
        if client_metadata:
            a2a_metadata["client_metadata"] = client_metadata

    return AgentTask(
        id=UUID(task_id) if task_id else uuid4(),
        title="A2A Message Task",
        description="Task created from A2A message",
        query=message_content,
        user_id=user_id,
        workspace_id=workspace_id,
        agent_id=agent_id,
        status="submitted",
        task_parameters={},
        metadata=a2a_metadata,
    )


_TASK_STATE_MAPPING = {
    "submitted": TaskState.SUBMITTED,
    "pending": TaskState.SUBMITTED,
    "running": TaskState.WORKING,
    "working": TaskState.WORKING,
    "input-required": TaskState.INPUT_REQUIRED,
    "input_required": TaskState.INPUT_REQUIRED,
    "auth-required": TaskState.AUTH_REQUIRED,
    "auth_required": TaskState.AUTH_REQUIRED,
    "completed": TaskState.COMPLETED,
    "failed": TaskState.FAILED,
    "rejected": TaskState.REJECTED,
    "cancelled": TaskState.CANCELED,
    "canceled": TaskState.CANCELED,
}


def a2a_context_id_for_task(task: AgentTask) -> str:
    """Return a stable, non-null A2A contextId for a task (spec requires non-null).

    Prefer an explicit context id stored in metadata, else fall back to the task id.
    """
    meta = task.metadata or {}
    return str(meta.get("a2a_context_id") or task.id)


def extract_final_text_from_task(task: AgentTask) -> str | None:
    """Extract the agent's final answer from a completed task.

    Canonical source (see ADR 2026-06-20): ``task.result["response"]``, produced by the
    Temporal workflow's ``state.final_response`` via ``get_task_with_workflow_status``.
    Falls back to ``final_response``/stringified result for robustness.
    """
    result = task.result
    if isinstance(result, dict):
        for key in ("response", "final_response", "result", "text"):
            value = result.get(key)
            if isinstance(value, str) and value.strip():
                return value
        return None
    if isinstance(result, str) and result.strip():
        return result
    return None


def extract_text_from_event_data(event_data: dict[str, Any]) -> str:
    """Pull text payload out of a streamed workflow event.

    Events arrive as DomainEvent dicts; the original workflow payload is nested under
    ``original_data`` (see ``publish_workflow_events_activity``). Final answers live in
    ``result``/``final_response``; incremental LLM output lives in ``chunk``.
    """
    payload = event_data.get("original_data")
    if not isinstance(payload, dict):
        payload = event_data if isinstance(event_data, dict) else {}
    for key in ("chunk", "content", "text", "result", "final_response", "delta"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


# Real workflow terminal event types. The feed yields unprefixed types (as
# stored in task_events); the ``workflow.*`` forms are kept for back-compat.
_TERMINAL_EVENT_STATES = {
    "workflow.WorkflowCompleted": TaskState.COMPLETED,
    "workflow.WorkflowFailed": TaskState.FAILED,
    "workflow.WorkflowCancelled": TaskState.CANCELED,
    "WorkflowCompleted": TaskState.COMPLETED,
    "WorkflowFailed": TaskState.FAILED,
    "WorkflowCancelled": TaskState.CANCELED,
}
# Incremental output event types.
_CHUNK_EVENT_TYPES = {"workflow.LLMCallChunk", "LLMCallChunk"}
# Terminal task event types the feed watches to end an A2A stream (unprefixed,
# as stored in task_events and emitted on the per-task stream).
_A2A_TERMINAL_TYPES = frozenset({"WorkflowCompleted", "WorkflowFailed", "WorkflowCancelled"})


def _sse(response: JSONRPCResponse) -> str:
    """Serialize a JSON-RPC response as an SSE ``data:`` frame."""
    return f"data: {response.model_dump_json(by_alias=True)}\n\n"


def map_workflow_event_to_sse(
    event: dict[str, Any],
    request_id: str | int | None,
    task_id: str,
    context_id: str | None,
) -> tuple[list[str], bool]:
    """Map a streamed workflow event to A2A SSE frames per ADR 2026-06-20.

    Returns ``(frames, is_terminal)``. Terminal events emit a final artifact-update
    (when text is present) followed by a final status-update with ``final=True``.
    """
    event_type = event.get("event_type", "")
    event_data = event.get("event_data", {}) or {}
    frames: list[str] = []

    state = _TERMINAL_EVENT_STATES.get(event_type)
    if state:
        if state == TaskState.COMPLETED:
            text = extract_text_from_event_data(event_data)
            if text:
                frames.append(
                    _sse(
                        JSONRPCResponse(
                            id=request_id,
                            result={
                                "artifactUpdate": StreamResponseArtifactUpdate(
                                    taskId=task_id,
                                    contextId=context_id,
                                    artifact=Artifact(
                                        artifactId=task_id,
                                        name="agent-response",
                                        parts=[TextPart(text=text)],
                                    ),
                                    append=False,
                                    lastChunk=True,
                                ).model_dump(by_alias=True),
                            },
                        )
                    )
                )
        frames.append(
            _sse(
                JSONRPCResponse(
                    id=request_id,
                    result={
                        "statusUpdate": StreamResponseStatusUpdate(
                            taskId=task_id,
                            contextId=context_id,
                            status=TaskStatus(state=state),
                        ).model_dump(by_alias=True),
                    },
                )
            )
        )
        return frames, True

    if event_type in _CHUNK_EVENT_TYPES:
        text = extract_text_from_event_data(event_data)
        if text:
            frames.append(
                _sse(
                    JSONRPCResponse(
                        id=request_id,
                        result={
                            "artifactUpdate": StreamResponseArtifactUpdate(
                                taskId=task_id,
                                contextId=context_id,
                                artifact=Artifact(
                                    artifactId=task_id,
                                    parts=[TextPart(text=text)],
                                ),
                                append=True,
                                lastChunk=False,
                            ).model_dump(by_alias=True),
                        },
                    )
                )
            )
        return frames, False

    # Any other workflow event → a working status update.
    frames.append(
        _sse(
            JSONRPCResponse(
                id=request_id,
                result={
                    "statusUpdate": StreamResponseStatusUpdate(
                        taskId=task_id,
                        contextId=context_id,
                        status=TaskStatus(state=TaskState.WORKING),
                    ).model_dump(by_alias=True),
                },
            )
        )
    )
    return frames, False


def convert_agent_task_to_a2a_task(task: AgentTask) -> Task:
    """Convert AgentTask to A2A protocol Task, mapping the final result onto the wire.

    For terminal-success tasks the final text is surfaced both as an ``Artifact`` and as
    ``status.message`` so both rich and spec-minimal clients can read it.
    """
    task_state = _TASK_STATE_MAPPING.get(task.status, TaskState.SUBMITTED)
    context_id = a2a_context_id_for_task(task)

    artifacts: list[Artifact] | None = None
    status_message: Message | None = None

    if task_state == TaskState.COMPLETED:
        final_text = extract_final_text_from_task(task)
        if final_text:
            artifacts = [
                Artifact(
                    artifactId=str(task.id),
                    name="agent-response",
                    parts=[TextPart(text=final_text)],
                )
            ]
            status_message = Message(role="AGENT", parts=[TextPart(text=final_text)])
    elif task_state in (TaskState.FAILED, TaskState.REJECTED):
        error_text = getattr(task, "error_message", None) or extract_final_text_from_task(task)
        if error_text:
            status_message = Message(role="AGENT", parts=[TextPart(text=error_text)])

    return Task(
        id=str(task.id),
        contextId=context_id,
        status=TaskStatus(state=task_state, message=status_message),
        artifacts=artifacts,
        history=None,
        metadata=task.metadata or {},
    )


async def _maybe_register_send_push_config(
    params, task_service, secret_manager, created_task
) -> None:
    """Register a push config supplied inline via configuration.pushNotificationConfig."""
    if secret_manager is None:
        return
    # v1.0.0: flat config under configuration.taskPushNotificationConfig.
    push_cfg = (params.get("configuration") or {}).get("taskPushNotificationConfig")
    if not push_cfg or not push_cfg.get("url"):
        return
    try:
        await register_push_config(task_service, secret_manager, created_task, push_cfg)
    except A2AValidationError as e:
        logger.warning(f"Ignoring invalid inline pushNotificationConfig: {e.message}")


async def handle_task_send(
    request_id, params, task_service, agent_id, auth_context, agent_service, secret_manager=None
):
    """Handle A2A task/send method with proper TaskService integration and validation."""
    start_time = time.time()

    # Log operation start
    log_a2a_operation("task_send", agent_id, auth_context, request_id, status="started")

    try:
        # Set user context from A2A auth for repository layer
        set_user_context_from_a2a_auth(auth_context)

        # Validate agent exists first (fail fast)
        await validate_agent_exists(agent_service, agent_id)

        # Validate and parse parameters
        message_send_params = validate_message_send_params(params)

        # Convert to task with proper metadata
        task = convert_a2a_message_to_task(
            message_send_params, agent_id, auth_context, "SendMessage", request_id
        )

        # Submit task through TaskService - this ensures Temporal workflow execution
        created_task = await task_service.submit_task(task)

        # Calculate duration
        duration_ms = (time.time() - start_time) * 1000

        # Log successful task creation with comprehensive metadata
        log_a2a_operation(
            "task_send",
            agent_id,
            auth_context,
            request_id,
            created_task.id,
            status="completed",
            duration_ms=duration_ms,
            extra_metadata={
                "task_title": created_task.title,
                "task_status": created_task.status,
                "message_length": len(task.query) if task.query else 0,
                "has_task_parameters": bool(created_task.task_parameters),
                "metadata_keys": list(created_task.metadata.keys())
                if created_task.metadata
                else [],
            },
        )

        # Register an inline push webhook if the client supplied one.
        await _maybe_register_send_push_config(params, task_service, secret_manager, created_task)

        # Create A2A protocol-compliant Task response (non-blocking: submitted state).
        # Callers retrieve the final result via tasks/get polling or message/stream.
        a2a_task = convert_agent_task_to_a2a_task(created_task)

        return SendMessageResponse(jsonrpc="2.0", id=request_id, result=a2a_task)
    except A2AValidationError as e:
        duration_ms = (time.time() - start_time) * 1000
        log_a2a_operation(
            "task_send",
            agent_id,
            auth_context,
            request_id,
            status="failed",
            duration_ms=duration_ms,
            error=str(e),
        )
        return create_error_response(request_id, e.code, e.message)
    except A2ATaskServiceError as e:
        duration_ms = (time.time() - start_time) * 1000
        log_a2a_operation(
            "task_send",
            agent_id,
            auth_context,
            request_id,
            status="failed",
            duration_ms=duration_ms,
            error=str(e),
        )
        return create_error_response(request_id, e.code, e.message)
    except ValueError as e:
        # Handle TaskService validation errors (e.g., agent not found in TaskService)
        duration_ms = (time.time() - start_time) * 1000
        log_a2a_operation(
            "task_send",
            agent_id,
            auth_context,
            request_id,
            status="failed",
            duration_ms=duration_ms,
            error=f"Invalid parameters: {e}",
        )
        return create_error_response(request_id, -32602, f"Invalid parameters: {e}")
    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        log_a2a_operation(
            "task_send",
            agent_id,
            auth_context,
            request_id,
            status="failed",
            duration_ms=duration_ms,
            error=f"Task submission failed: {e}",
        )
        return create_error_response(request_id, -32603, f"Task submission failed: {e}")


async def handle_message_send(
    request_id, params, task_service, agent_id, auth_context, agent_service, secret_manager=None
):
    """Handle A2A message/send method with proper TaskService integration and validation."""
    start_time = time.time()

    # Log operation start
    log_a2a_operation("message_send", agent_id, auth_context, request_id, status="started")

    try:
        # Set user context from A2A auth for repository layer
        set_user_context_from_a2a_auth(auth_context)

        # Validate agent exists first (fail fast)
        await validate_agent_exists(agent_service, agent_id)

        # Validate message structure
        message_data = params.get("message")
        if not message_data:
            raise A2AValidationError("Missing required parameter: message", -32602)

        # Extract and validate message parts
        parts = message_data.get("parts", [])
        if not parts:
            raise A2AValidationError("Message must contain at least one part", -32602)

        text_content = _extract_text_from_parts(parts)
        if not text_content.strip():
            raise A2AValidationError("Message must contain non-empty text content", -32602)

        # Create validated message
        message = Message(role="USER", parts=[TextPart(text=text_content)])
        # Include optional metadata from params (e.g., requires_human_approval)
        message_params = MessageSendParams(
            message=message, contextId=None, metadata=params.get("metadata")
        )

        # Convert to task with proper metadata
        task = convert_a2a_message_to_task(
            message_params, agent_id, auth_context, "SendMessage", request_id
        )

        # Submit task through TaskService - this ensures Temporal workflow execution
        created_task = await task_service.submit_task(task)

        # Calculate duration
        duration_ms = (time.time() - start_time) * 1000

        # Log successful message task creation with comprehensive metadata
        log_a2a_operation(
            "message_send",
            agent_id,
            auth_context,
            request_id,
            created_task.id,
            status="completed",
            duration_ms=duration_ms,
            extra_metadata={
                "task_title": created_task.title,
                "task_status": created_task.status,
                "message_length": len(text_content),
                "message_parts_count": len(parts),
                "has_task_parameters": bool(created_task.task_parameters),
                "metadata_keys": list(created_task.metadata.keys())
                if created_task.metadata
                else [],
            },
        )

        # Register an inline push webhook if the client supplied one.
        await _maybe_register_send_push_config(params, task_service, secret_manager, created_task)

        # Create A2A protocol-compliant Task response (non-blocking: submitted state).
        # Callers retrieve the final result via tasks/get polling or message/stream.
        a2a_task = convert_agent_task_to_a2a_task(created_task)

        return SendMessageResponse(jsonrpc="2.0", id=request_id, result=a2a_task)
    except A2AValidationError as e:
        duration_ms = (time.time() - start_time) * 1000
        log_a2a_operation(
            "message_send",
            agent_id,
            auth_context,
            request_id,
            status="failed",
            duration_ms=duration_ms,
            error=str(e),
        )
        return create_error_response(request_id, e.code, e.message)
    except A2ATaskServiceError as e:
        duration_ms = (time.time() - start_time) * 1000
        log_a2a_operation(
            "message_send",
            agent_id,
            auth_context,
            request_id,
            status="failed",
            duration_ms=duration_ms,
            error=str(e),
        )
        return create_error_response(request_id, e.code, e.message)
    except ValueError as e:
        # Handle TaskService validation errors (e.g., agent not found in TaskService)
        duration_ms = (time.time() - start_time) * 1000
        log_a2a_operation(
            "message_send",
            agent_id,
            auth_context,
            request_id,
            status="failed",
            duration_ms=duration_ms,
            error=f"Invalid parameters: {e}",
        )
        return create_error_response(request_id, -32602, f"Invalid parameters: {e}")
    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        log_a2a_operation(
            "message_send",
            agent_id,
            auth_context,
            request_id,
            status="failed",
            duration_ms=duration_ms,
            error=f"Message send failed: {e}",
        )
        return create_error_response(request_id, -32603, f"Message send failed: {e}")


async def handle_message_stream_sse(
    request,
    request_id,
    params,
    task_service,
    agent_id,
    auth_context,
    agent_service,
    secret_manager=None,
) -> JSONRPCResponse | Response:
    """Handle A2A message/stream method with proper TaskService integration.

    Includes validation and real event streaming.
    """
    start_time = time.time()

    # Log operation start
    log_a2a_operation("message_stream", agent_id, auth_context, request_id, status="started")

    try:
        # Set user context from A2A auth for repository layer
        set_user_context_from_a2a_auth(auth_context)

        # Validate agent exists first (fail fast)
        await validate_agent_exists(agent_service, agent_id)

        # Validate message structure
        message_data = params.get("message")
        if not message_data:
            raise A2AValidationError("Missing required parameter: message", -32602)

        # Extract and validate message parts
        parts = message_data.get("parts", [])
        if not parts:
            raise A2AValidationError("Message must contain at least one part", -32602)

        text_content = _extract_text_from_parts(parts)
        if not text_content.strip():
            raise A2AValidationError("Message must contain non-empty text content", -32602)

        # Create validated message
        message = Message(role="USER", parts=[TextPart(text=text_content)])
        # Include optional metadata from params (e.g., requires_human_approval)
        message_params = MessageSendParams(
            message=message, contextId=None, metadata=params.get("metadata")
        )

        # Create task with proper A2A metadata
        task = convert_a2a_message_to_task(
            message_params,
            agent_id,
            auth_context,
            "SendStreamingMessage",
            request_id,
            params.get("id"),  # Use provided task ID if available
        )

        # Submit task through TaskService - this ensures Temporal workflow execution
        created_task = await task_service.submit_task(task)

        # Register an inline push webhook if the client supplied one.
        await _maybe_register_send_push_config(params, task_service, secret_manager, created_task)

        # Calculate task creation duration
        task_creation_duration_ms = (time.time() - start_time) * 1000

        # Log successful streaming task creation with comprehensive metadata
        log_a2a_operation(
            "message_stream",
            agent_id,
            auth_context,
            request_id,
            created_task.id,
            status="task_created",
            duration_ms=task_creation_duration_ms,
            extra_metadata={
                "task_title": created_task.title,
                "task_status": created_task.status,
                "message_length": len(text_content),
                "message_parts_count": len(parts),
                "streaming": True,
                "has_task_parameters": bool(created_task.task_parameters),
                "metadata_keys": list(created_task.metadata.keys())
                if created_task.metadata
                else [],
            },
        )

        task_context_id = a2a_context_id_for_task(created_task)

        async def event_stream():
            """Stream events in A2A v1.0.0 StreamResponse SSE format."""
            event_count = 0
            stream_start_time = time.time()

            try:
                # 1. Send initial "task" event (wrapped by member name)
                initial = JSONRPCResponse(
                    id=request_id,
                    result={
                        "task": StreamResponseTask(
                            id=str(created_task.id),
                            contextId=task_context_id,
                            status=TaskStatus(state=TaskState.SUBMITTED),
                        ).model_dump(by_alias=True),
                    },
                )
                yield f"data: {initial.model_dump_json(by_alias=True)}\n\n"
                event_count += 1

                # 2. Stream task events (catch-up + live), mapping each to A2A
                # SSE frames. Chunks are included so A2A streams live tokens.
                async for env in open_task_event_feed(
                    created_task.id, terminal_types=_A2A_TERMINAL_TYPES
                ):
                    event_count += 1
                    frames, is_terminal = map_workflow_event_to_sse(
                        {"event_type": env.event_type, "event_data": env.data},
                        request_id,
                        str(created_task.id),
                        task_context_id,
                    )
                    for frame in frames:
                        yield frame
                    if is_terminal:
                        break

                # Log streaming completion
                stream_duration_ms = (time.time() - stream_start_time) * 1000
                log_a2a_operation(
                    "message_stream",
                    agent_id,
                    auth_context,
                    request_id,
                    created_task.id,
                    status="stream_completed",
                    duration_ms=stream_duration_ms,
                    extra_metadata={"events_streamed": event_count},
                )

            except Exception as stream_error:
                stream_duration_ms = (time.time() - stream_start_time) * 1000
                log_a2a_operation(
                    "message_stream",
                    agent_id,
                    auth_context,
                    request_id,
                    created_task.id,
                    status="stream_failed",
                    duration_ms=stream_duration_ms,
                    error=str(stream_error),
                )
                error_resp = JSONRPCResponse(
                    id=request_id,
                    error=JSONRPCError(code=-32603, message=str(stream_error)),
                )
                yield f"data: {error_resp.model_dump_json(by_alias=True)}\n\n"

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Access-Control-Allow-Origin": "*",
            },
        )
    except A2AValidationError as e:
        duration_ms = (time.time() - start_time) * 1000
        log_a2a_operation(
            "message_stream",
            agent_id,
            auth_context,
            request_id,
            status="failed",
            duration_ms=duration_ms,
            error=str(e),
        )

        error_code = e.code
        error_message = e.message

        async def error_stream():
            error_data = {"event": "error", "code": error_code, "message": error_message}
            yield f"data: {json.dumps(error_data)}\n\n"

        return StreamingResponse(error_stream(), media_type="text/event-stream")
    except A2ATaskServiceError as e:
        duration_ms = (time.time() - start_time) * 1000
        log_a2a_operation(
            "message_stream",
            agent_id,
            auth_context,
            request_id,
            status="failed",
            duration_ms=duration_ms,
            error=str(e),
        )

        error_code = e.code
        error_message = e.message

        async def error_stream():
            error_data = {"event": "error", "code": error_code, "message": error_message}
            yield f"data: {json.dumps(error_data)}\n\n"

        return StreamingResponse(error_stream(), media_type="text/event-stream")
    except ValueError as e:
        # Handle TaskService validation errors (e.g., agent not found in TaskService)
        duration_ms = (time.time() - start_time) * 1000
        # Log the full validation detail server-side; return a generic
        # JSON-RPC invalid-params message to the caller to avoid leaking
        # internal exception details.
        log_a2a_operation(
            "message_stream",
            agent_id,
            auth_context,
            request_id,
            status="failed",
            duration_ms=duration_ms,
            error=f"Invalid parameters: {e}",
        )

        async def error_stream():
            error_data = {
                "event": "error",
                "code": -32602,
                "message": "Invalid parameters",
            }
            yield f"data: {json.dumps(error_data)}\n\n"

        return StreamingResponse(error_stream(), media_type="text/event-stream")
    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        log_a2a_operation(
            "message_stream",
            agent_id,
            auth_context,
            request_id,
            status="failed",
            duration_ms=duration_ms,
            error=str(e),
        )

        async def error_stream():
            yield f"data: {json.dumps({'event': 'error', 'code': -32603, 'message': str(e)})}\n\n"  # noqa: F821

        return StreamingResponse(error_stream(), media_type="text/event-stream")


async def handle_task_get(request_id, params, task_service, agent_id, auth_context):
    """Handle A2A tasks/get method with current workflow status and proper validation."""
    start_time = time.time()

    try:
        # Validate and parse task ID
        task_id = validate_task_id_param(params)

        # Log operation start
        log_a2a_operation("task_get", agent_id, auth_context, request_id, task_id, status="started")

        # Get task with current workflow status - this ensures we get the most up-to-date
        # status from Temporal workflows rather than just the database status
        task = await task_service.get_task_with_workflow_status(task_id)

        if not task:
            duration_ms = (time.time() - start_time) * 1000
            log_a2a_operation(
                "task_get",
                agent_id,
                auth_context,
                request_id,
                task_id,
                status="failed",
                duration_ms=duration_ms,
                error="Task not found",
            )
            return create_error_response(request_id, -32001, f"Task not found: {task_id}")

        # Calculate duration
        duration_ms = (time.time() - start_time) * 1000

        # Log successful task retrieval
        log_a2a_operation(
            "task_get",
            agent_id,
            auth_context,
            request_id,
            task_id,
            status="completed",
            duration_ms=duration_ms,
            extra_metadata={
                "task_status": task.status,
                "task_title": task.title,
                "has_result": bool(task.result),
                "has_error": bool(task.error_message),
                "metadata_keys": list(task.metadata.keys()) if task.metadata else [],
            },
        )

        # Convert AgentTask to A2A protocol Task format
        a2a_task = convert_agent_task_to_a2a_task(task)

        return GetTaskResponse(jsonrpc="2.0", id=request_id, result=a2a_task)
    except A2AValidationError as e:
        duration_ms = (time.time() - start_time) * 1000
        log_a2a_operation(
            "task_get",
            agent_id,
            auth_context,
            request_id,
            status="failed",
            duration_ms=duration_ms,
            error=str(e),
        )
        return create_error_response(request_id, e.code, e.message)
    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        log_a2a_operation(
            "task_get",
            agent_id,
            auth_context,
            request_id,
            status="failed",
            duration_ms=duration_ms,
            error=f"Task get failed: {e}",
        )
        return create_error_response(request_id, -32603, f"Task get failed: {e}")


async def handle_task_cancel(request_id, params, task_service, agent_id, auth_context):
    """Handle A2A tasks/cancel method with TaskService cancellation and proper validation."""
    start_time = time.time()

    try:
        # Validate and parse task ID
        task_id = validate_task_id_param(params)

        # Log operation start
        log_a2a_operation(
            "task_cancel", agent_id, auth_context, request_id, task_id, status="started"
        )

        # Get task with current workflow status to ensure we have the most up-to-date status
        task = await task_service.get_task_with_workflow_status(task_id)
        if not task:
            duration_ms = (time.time() - start_time) * 1000
            log_a2a_operation(
                "task_cancel",
                agent_id,
                auth_context,
                request_id,
                task_id,
                status="failed",
                duration_ms=duration_ms,
                error="Task not found",
            )
            return create_error_response(request_id, -32001, f"Task not found: {task_id}")

        # Check if task can be cancelled based on current workflow status
        if task.status in ["completed", "failed", "cancelled"]:
            duration_ms = (time.time() - start_time) * 1000
            error_msg = f"Task cannot be cancelled (current status: {task.status})"
            log_a2a_operation(
                "task_cancel",
                agent_id,
                auth_context,
                request_id,
                task_id,
                status="failed",
                duration_ms=duration_ms,
                error=error_msg,
                extra_metadata={"current_status": task.status},
            )
            return create_error_response(request_id, -32002, error_msg)

        # Use TaskService cancellation which properly handles Temporal workflow cancellation
        success = await task_service.cancel_task(task_id)

        # Calculate duration
        duration_ms = (time.time() - start_time) * 1000

        if success:
            # Get the updated task to return current state
            updated_task = await task_service.get_task_with_workflow_status(task_id)

            # Log successful cancellation
            log_a2a_operation(
                "task_cancel",
                agent_id,
                auth_context,
                request_id,
                task_id,
                status="completed",
                duration_ms=duration_ms,
                extra_metadata={
                    "previous_status": task.status,
                    "new_status": updated_task.status if updated_task else "unknown",
                    "cancellation_successful": True,
                },
            )

            # Convert to A2A protocol Task format
            a2a_task = convert_agent_task_to_a2a_task(updated_task)

            return CancelTaskResponse(jsonrpc="2.0", id=request_id, result=a2a_task)
        else:
            log_a2a_operation(
                "task_cancel",
                agent_id,
                auth_context,
                request_id,
                task_id,
                status="failed",
                duration_ms=duration_ms,
                error="Task cancellation failed",
                extra_metadata={"cancellation_successful": False},
            )
            return create_error_response(request_id, -32603, "Task cancellation failed")

    except A2AValidationError as e:
        duration_ms = (time.time() - start_time) * 1000
        log_a2a_operation(
            "task_cancel",
            agent_id,
            auth_context,
            request_id,
            status="failed",
            duration_ms=duration_ms,
            error=str(e),
        )
        return create_error_response(request_id, e.code, e.message)
    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        log_a2a_operation(
            "task_cancel",
            agent_id,
            auth_context,
            request_id,
            status="failed",
            duration_ms=duration_ms,
            error=f"Task cancel failed: {e}",
        )
        return create_error_response(request_id, -32603, f"Task cancel failed: {e}")


async def handle_task_resubscribe(
    request, request_id, params, task_service, agent_id, auth_context
):
    """Handle tasks/resubscribe — re-attach to SSE stream for an existing task."""
    time.time()
    log_a2a_operation("task_resubscribe", agent_id, auth_context, request_id, status="started")

    try:
        task_id = validate_task_id_param(params)
        set_user_context_from_a2a_auth(auth_context)

        task = await task_service.get_task_with_workflow_status(task_id)
        if not task:
            return create_error_response(request_id, -32001, f"Task not found: {task_id}")

        context_id = a2a_context_id_for_task(task)

        # If task already terminal, replay the final result then a final status update.
        if task.status in ("completed", "failed", "cancelled", "canceled", "rejected"):
            a2a_task = convert_agent_task_to_a2a_task(task)

            async def done_stream():
                if a2a_task.artifacts:
                    for artifact in a2a_task.artifacts:
                        yield _sse(
                            JSONRPCResponse(
                                id=request_id,
                                result={
                                    "artifactUpdate": StreamResponseArtifactUpdate(
                                        taskId=str(task_id),
                                        contextId=context_id,
                                        artifact=artifact,
                                        append=False,
                                        lastChunk=True,
                                    ).model_dump(by_alias=True),
                                },
                            )
                        )
                yield _sse(
                    JSONRPCResponse(
                        id=request_id,
                        result={
                            "statusUpdate": StreamResponseStatusUpdate(
                                taskId=str(task_id),
                                contextId=context_id,
                                status=a2a_task.status,
                            ).model_dump(by_alias=True),
                        },
                    )
                )

            return StreamingResponse(
                done_stream(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
            )

        # Stream task events (catch-up + live) for active task
        async def event_stream():
            async for env in open_task_event_feed(
                task_id, terminal_types=_A2A_TERMINAL_TYPES
            ):
                frames, is_terminal = map_workflow_event_to_sse(
                    {"event_type": env.event_type, "event_data": env.data},
                    request_id,
                    str(task_id),
                    context_id,
                )
                for frame in frames:
                    yield frame
                if is_terminal:
                    break

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
        )

    except A2AValidationError as e:
        return create_error_response(request_id, e.code, e.message)
    except Exception as e:
        return create_error_response(request_id, -32603, f"Resubscribe failed: {e}")


async def handle_task_list(request_id, params, task_service, agent_id, auth_context):
    """Handle tasks/list — list tasks for an agent."""
    set_user_context_from_a2a_auth(auth_context)

    limit = params.get("limit", 50)
    offset = params.get("offset", 0)

    tasks = await task_service.get_agent_tasks(agent_id, limit=limit, offset=offset)
    a2a_tasks = [convert_agent_task_to_a2a_task(t).model_dump(by_alias=True) for t in tasks]

    return JSONRPCResponse(jsonrpc="2.0", id=request_id, result=a2a_tasks)


async def register_push_config(
    task_service,
    secret_manager: BaseSecretManager,
    task,
    push_config: dict[str, Any],
) -> dict[str, Any]:
    """Validate, persist (non-secret in task_parameters, token in secret store), and
    return a stored push config dict. Raises A2AValidationError on bad input.
    """
    url = push_config.get("url")
    if not url:
        raise A2AValidationError("pushNotificationConfig.url is required", -32602)
    try:
        validate_outbound_url(url)
    except UnsafeUrlError as e:
        raise A2AValidationError(f"Unsafe webhook url: {e}", -32602) from e

    new_params, stored = upsert_push_config(task.task_parameters, url, push_config.get("id"))
    token = push_config.get("token")
    if token:
        await secret_manager.set_secret(push_token_secret_name(str(task.id), stored["id"]), token)
    await task_service.task_repository.update_by_id(task.id, TaskUpdate(task_parameters=new_params))
    return stored


async def handle_push_config_set(
    request_id, params, task_service, agent_id, auth_context, secret_manager
):
    """Handle CreateTaskPushNotificationConfig (flat v1.0.0 params)."""
    set_user_context_from_a2a_auth(auth_context)
    task_id = params.get("taskId")
    # v1.0.0 config is flat: {taskId, id?, url, token?, ...}
    push_config = {
        "id": params.get("id"),
        "url": params.get("url"),
        "token": params.get("token"),
    }
    if not task_id:
        return create_error_response(request_id, -32602, "Missing required parameter: taskId")
    try:
        task = await task_service.get_task(UUID(task_id))
    except ValueError:
        return create_error_response(request_id, -32602, f"Invalid task ID: {task_id}")
    if not task:
        return create_error_response(request_id, -32001, f"Task not found: {task_id}")
    try:
        stored = await register_push_config(task_service, secret_manager, task, push_config)
    except A2AValidationError as e:
        return create_error_response(request_id, e.code, e.message)
    return JSONRPCResponse(
        jsonrpc="2.0", id=request_id, result=task_push_config_result(task_id, stored)
    )


async def handle_push_config_get(request_id, params, task_service, agent_id, auth_context):
    """Handle tasks/pushNotificationConfig/get."""
    set_user_context_from_a2a_auth(auth_context)
    task_id = params.get("id") or params.get("taskId")
    config_id = params.get("pushNotificationConfigId")
    if not task_id:
        return create_error_response(request_id, -32602, "Missing required parameter: id")
    try:
        task = await task_service.get_task(UUID(task_id))
    except ValueError:
        return create_error_response(request_id, -32602, f"Invalid task ID: {task_id}")
    if not task:
        return create_error_response(request_id, -32001, f"Task not found: {task_id}")

    if config_id:
        cfg = get_push_config(task.task_parameters, config_id)
    else:
        configs = list_push_configs(task.task_parameters)
        cfg = configs[0] if configs else None
    if not cfg:
        return create_error_response(request_id, -32001, "Push notification config not found")
    return JSONRPCResponse(
        jsonrpc="2.0", id=request_id, result=task_push_config_result(task_id, cfg)
    )


async def handle_push_config_list(request_id, params, task_service, agent_id, auth_context):
    """Handle tasks/pushNotificationConfig/list — array of configs for a task."""
    set_user_context_from_a2a_auth(auth_context)
    task_id = params.get("id") or params.get("taskId")
    if not task_id:
        return create_error_response(request_id, -32602, "Missing required parameter: id")
    try:
        task = await task_service.get_task(UUID(task_id))
    except ValueError:
        return create_error_response(request_id, -32602, f"Invalid task ID: {task_id}")
    if not task:
        return create_error_response(request_id, -32001, f"Task not found: {task_id}")
    result = [
        task_push_config_result(task_id, cfg) for cfg in list_push_configs(task.task_parameters)
    ]
    return JSONRPCResponse(jsonrpc="2.0", id=request_id, result=result)


async def handle_push_config_delete(
    request_id, params, task_service, agent_id, auth_context, secret_manager
):
    """Handle tasks/pushNotificationConfig/delete — returns null on success."""
    set_user_context_from_a2a_auth(auth_context)
    task_id = params.get("id") or params.get("taskId")
    config_id = params.get("pushNotificationConfigId")
    if not task_id or not config_id:
        return create_error_response(
            request_id, -32602, "Missing required parameters: id, pushNotificationConfigId"
        )
    try:
        task = await task_service.get_task(UUID(task_id))
    except ValueError:
        return create_error_response(request_id, -32602, f"Invalid task ID: {task_id}")
    if not task:
        return create_error_response(request_id, -32001, f"Task not found: {task_id}")

    new_params, removed = delete_push_config(task.task_parameters, config_id)
    if removed:
        await task_service.task_repository.update_by_id(
            task.id, TaskUpdate(task_parameters=new_params)
        )
        try:
            await secret_manager.set_secret(push_token_secret_name(str(task_id), config_id), "")
        except Exception:  # noqa: S110 — token cleanup is best-effort
            pass
    return JSONRPCResponse(jsonrpc="2.0", id=request_id, result=None)


async def handle_agent_card(request_id, params, agent_service, agent_id, base_url, auth_context):
    """Handle A2A GetExtendedAgentCard method.

    Includes current agent data and proper validation.
    """
    start_time = time.time()

    # Log operation start
    log_a2a_operation("agent_card", agent_id, auth_context, request_id, status="started")

    try:
        # Validate agent exists first (fail fast)
        await validate_agent_exists(agent_service, agent_id)

        # Get current agent details
        agent = await agent_service.get(agent_id)
        if not agent:
            raise A2AValidationError(f"Agent with ID {agent_id} not found", -32602)

        # Build current capabilities based on agent configuration
        capabilities = AgentCapabilities(
            streaming=True,  # All agents support streaming through A2A
            pushNotifications=True,  # Webhook push via channel-delivery pipeline
            extendedAgentCard=True,  # GetExtendedAgentCard supported
        )

        # Build skills based on agent configuration and tools
        skills = []

        # Base text processing skill for all agents
        skills.append(
            AgentSkill(
                id="text-processing",
                name="Text Processing",
                description=f"Process and respond to text messages using {agent.name}",
                tags=["text", "chat"],
                inputModes=["text"],
                outputModes=["text"],
            )
        )

        # Add tool-based skills if agent has tools configured
        if agent.tools and isinstance(agent.tools, list) and len(agent.tools) > 0:
            skills.append(
                AgentSkill(
                    id="tool-execution",
                    name="Tool Execution",
                    description=f"Execute tools and integrations using {agent.name}",
                    tags=["tools", "integration"],
                    inputModes=["text"],
                    outputModes=["text", "data"],
                )
            )

        # Add planning skill if agent has planning enabled
        if agent.planning:
            skills.append(
                AgentSkill(
                    id="task-planning",
                    name="Task Planning",
                    description=f"Break down complex tasks into steps using {agent.name}",
                    tags=["planning"],
                    inputModes=["text"],
                    outputModes=["text"],
                )
            )

        # Calculate duration
        duration_ms = (time.time() - start_time) * 1000

        # Log successful agent card retrieval with current agent data
        log_a2a_operation(
            "agent_card",
            agent_id,
            auth_context,
            request_id,
            status="completed",
            duration_ms=duration_ms,
            extra_metadata={
                "agent_name": agent.name,
                "agent_status": agent.status,
                "agent_description_length": len(agent.description) if agent.description else 0,
                "model_id": agent.model_id,
                "has_tools": bool(
                    agent.tools and isinstance(agent.tools, list) and len(agent.tools) > 0
                ),
                "has_planning": bool(agent.planning),
                "skills_count": len(skills),
                "base_url": base_url,
                "capabilities": ["streaming", "pushNotifications", "extendedAgentCard"],
            },
        )

        from agentarea_common.utils.types import AgentProvider

        # Include current agent status and model information in description
        enhanced_description = (
            agent.description or f"AI agent powered by {agent.model_id or 'language model'}"
        )
        if agent.status and agent.status != "active":
            enhanced_description += f" (Status: {agent.status})"

        rpc_url = f"{base_url}/api/v1/agents/{agent_id}/a2a/rpc"
        agent_card = AgentCard(
            name=agent.name,
            description=enhanced_description,
            supportedInterfaces=[
                AgentInterface(url=rpc_url, protocolBinding="JSONRPC", protocolVersion="1.0")
            ],
            version="1.0.0",
            provider=AgentProvider(
                organization="AgentArea", url=f"{base_url}/api/v1/agents/{agent_id}"
            ),
            documentationUrl=None,
            capabilities=capabilities,
            defaultInputModes=["text/plain", "application/json"],
            defaultOutputModes=["text/plain", "application/json"],
            skills=skills,
            securitySchemes=None,
        )
        return AgentAuthenticatedExtendedCardResponse(
            jsonrpc="2.0", id=request_id, result=agent_card
        )
    except A2AValidationError as e:
        duration_ms = (time.time() - start_time) * 1000
        log_a2a_operation(
            "agent_card",
            agent_id,
            auth_context,
            request_id,
            status="failed",
            duration_ms=duration_ms,
            error=str(e),
        )
        return create_error_response(request_id, e.code, e.message)
    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        log_a2a_operation(
            "agent_card",
            agent_id,
            auth_context,
            request_id,
            status="failed",
            duration_ms=duration_ms,
            error=f"Agent card retrieval failed: {e}",
        )
        return create_error_response(request_id, -32603, f"Agent card retrieval failed: {e}")


async def _dispatch_rpc_method(
    method: str,
    *,
    request_id,
    params,
    request,
    task_service,
    agent_service,
    agent_id,
    auth_context,
    secret_manager,
):
    """Dispatch A2A RPC method calls with proper error handling."""
    base_url = f"{request.url.scheme}://{request.url.netloc}" if request else None
    handlers = {
        "SendMessage": lambda: handle_message_send(
            request_id, params, task_service, agent_id, auth_context, agent_service, secret_manager
        ),
        "SendStreamingMessage": lambda: handle_message_stream_sse(
            request,
            request_id,
            params,
            task_service,
            agent_id,
            auth_context,
            agent_service,
            secret_manager,
        ),
        "GetTask": lambda: handle_task_get(
            request_id, params, task_service, agent_id, auth_context
        ),
        "CancelTask": lambda: handle_task_cancel(
            request_id, params, task_service, agent_id, auth_context
        ),
        "SubscribeToTask": lambda: handle_task_resubscribe(
            request, request_id, params, task_service, agent_id, auth_context
        ),
        "ListTasks": lambda: handle_task_list(
            request_id, params, task_service, agent_id, auth_context
        ),
        "CreateTaskPushNotificationConfig": lambda: handle_push_config_set(
            request_id, params, task_service, agent_id, auth_context, secret_manager
        ),
        "GetTaskPushNotificationConfig": lambda: handle_push_config_get(
            request_id, params, task_service, agent_id, auth_context
        ),
        "ListTaskPushNotificationConfigs": lambda: handle_push_config_list(
            request_id, params, task_service, agent_id, auth_context
        ),
        "DeleteTaskPushNotificationConfig": lambda: handle_push_config_delete(
            request_id, params, task_service, agent_id, auth_context, secret_manager
        ),
        "GetExtendedAgentCard": lambda: handle_agent_card(
            request_id, params, agent_service, agent_id, base_url, auth_context
        ),
    }
    handler = handlers.get(method)
    if handler:
        return await handler()

    # Method not found - log and return standardized error
    log_a2a_operation(
        "unknown_method",
        agent_id,
        auth_context,
        request_id,
        status="failed",
        error=f"Method not found: {method}",
    )
    return create_error_response(request_id, -32601, f"Method not found: {method}")


@router.post("/rpc", response_model=None)
async def handle_agent_jsonrpc(
    agent_id: UUID,
    request: Request,
    auth_context: A2AAuthContext = Depends(require_a2a_execute_auth),
    task_service: TaskService = Depends(get_task_service),
    agent_service: AgentService = Depends(get_agent_service),
    secret_manager: BaseSecretManager = Depends(get_secret_manager),
) -> JSONRPCResponse | Response:
    """Handle A2A JSON-RPC requests with comprehensive error handling and validation."""
    request_start_time = time.time()
    request_id = None
    method = None

    try:
        # Parse request body
        body = await request.body()
        if not body:
            log_a2a_operation(
                "rpc_request",
                agent_id,
                auth_context,
                None,
                status="failed",
                error="Empty request body",
            )
            return create_error_response(None, -32600, "Empty request body")

        try:
            request_data = json.loads(body)
        except json.JSONDecodeError as e:
            log_a2a_operation(
                "rpc_request",
                agent_id,
                auth_context,
                None,
                status="failed",
                error=f"JSON parse error: {e}",
            )
            return create_error_response(None, -32700, "Parse error: Invalid JSON")

        # A2A v1.0.0: read the A2A-Version header. Absent → treat as 1.0 (we only
        # serve 1.0). Present and not starting with "1." → version not supported.
        a2a_version = request.headers.get("A2A-Version")
        if a2a_version is not None and not a2a_version.startswith("1."):
            log_a2a_operation(
                "rpc_request",
                agent_id,
                auth_context,
                request_data.get("id"),
                status="failed",
                error=f"Unsupported A2A version: {a2a_version}",
            )
            return create_error_response(
                request_data.get("id"),
                -32009,
                f"A2A version not supported: {a2a_version}",
            )

        # Validate JSON-RPC request structure
        try:
            rpc_request = JSONRPCRequest(**request_data)
        except ValidationError as e:
            error_details = []
            for error in e.errors():
                field = ".".join(str(x) for x in error["loc"])
                error_details.append(f"{field}: {error['msg']}")
            error_msg = f"Invalid request: {'; '.join(error_details)}"
            log_a2a_operation(
                "rpc_request",
                agent_id,
                auth_context,
                request_data.get("id"),
                status="failed",
                error=error_msg,
            )
            return create_error_response(request_data.get("id"), -32600, error_msg)

        method = rpc_request.method
        params = rpc_request.params or {}
        request_id = rpc_request.id

        # Log RPC request start with comprehensive metadata
        log_a2a_operation(
            "rpc_request",
            agent_id,
            auth_context,
            request_id,
            status="started",
            extra_metadata={
                "method": method,
                "params_keys": list(params.keys()) if isinstance(params, dict) else [],
                "request_size_bytes": len(body),
                "client_ip": request.client.host if request.client else None,
                "user_agent": request.headers.get("user-agent"),
                "content_type": request.headers.get("content-type"),
            },
        )

        # Set user context from A2A auth for repository layer
        # (for methods that don't set it themselves)
        if method not in ["SendMessage", "SendStreamingMessage"]:
            set_user_context_from_a2a_auth(auth_context)

        # Dispatch to method handler
        result = await _dispatch_rpc_method(
            method,
            request_id=request_id,
            params=params,
            request=request,
            task_service=task_service,
            agent_service=agent_service,
            agent_id=agent_id,
            auth_context=auth_context,
            secret_manager=secret_manager,
        )

        # Calculate total request duration
        request_duration_ms = (time.time() - request_start_time) * 1000

        # Log successful RPC completion
        log_a2a_operation(
            "rpc_request",
            agent_id,
            auth_context,
            request_id,
            status="completed",
            duration_ms=request_duration_ms,
            extra_metadata={
                "method": method,
                "result_type": type(result).__name__,
                "is_streaming_response": isinstance(result, Response)
                and result.media_type == "text/event-stream",
            },
        )

        return result

    except A2AValidationError as e:
        request_duration_ms = (time.time() - request_start_time) * 1000
        log_a2a_operation(
            "rpc_request",
            agent_id,
            auth_context,
            request_id,
            status="failed",
            duration_ms=request_duration_ms,
            error=str(e),
            extra_metadata={"method": method},
        )
        return create_error_response(request_id, e.code, e.message)
    except A2ATaskServiceError as e:
        request_duration_ms = (time.time() - request_start_time) * 1000
        log_a2a_operation(
            "rpc_request",
            agent_id,
            auth_context,
            request_id,
            status="failed",
            duration_ms=request_duration_ms,
            error=str(e),
            extra_metadata={"method": method},
        )
        return create_error_response(request_id, e.code, e.message)
    except Exception as e:
        request_duration_ms = (time.time() - request_start_time) * 1000
        log_a2a_operation(
            "rpc_request",
            agent_id,
            auth_context,
            request_id,
            status="failed",
            duration_ms=request_duration_ms,
            error=f"Internal error: {e}",
            extra_metadata={"method": method},
        )
        return create_error_response(request_id, -32603, f"Internal error: {e}")


@router.get("/well-known")
async def get_agent_well_known(
    agent_id: UUID,
    request: Request,
    auth_context: A2AAuthContext = Depends(allow_public_access),
    agent_service: AgentService = Depends(get_agent_service),
) -> AgentCard:
    """Get current agent discovery information with proper validation and error handling."""
    start_time = time.time()

    # Log well-known request start
    log_a2a_operation(
        "well_known",
        agent_id,
        auth_context,
        status="started",
        extra_metadata={
            "endpoint": "well-known",
            "client_ip": request.client.host if request.client else None,
            "user_agent": request.headers.get("user-agent"),
        },
    )

    try:
        # Validate agent exists first (fail fast)
        await validate_agent_exists(agent_service, agent_id)

        # Get current agent details
        agent = await agent_service.get(agent_id)
        if not agent:
            raise A2AValidationError(f"Agent with ID {agent_id} not found", -32602)

        # Build current capabilities based on agent configuration
        capabilities = AgentCapabilities(
            streaming=True,  # All agents support streaming through A2A
            pushNotifications=True,  # Webhook push via channel-delivery pipeline
            extendedAgentCard=True,  # GetExtendedAgentCard supported
        )

        # Build skills based on current agent configuration and tools
        skills = []

        # Base text processing skill for all agents
        skills.append(
            AgentSkill(
                id="text-processing",
                name="Text Processing",
                description=f"Process and respond to text messages using {agent.name}",
                tags=["text", "chat"],
                inputModes=["text"],
                outputModes=["text"],
            )
        )

        # Add tool-based skills if agent has tools configured
        if agent.tools and isinstance(agent.tools, list) and len(agent.tools) > 0:
            skills.append(
                AgentSkill(
                    id="tool-execution",
                    name="Tool Execution",
                    description=f"Execute tools and integrations using {agent.name}",
                    tags=["tools", "integration"],
                    inputModes=["text"],
                    outputModes=["text", "data"],
                )
            )

        # Add planning skill if agent has planning enabled
        if agent.planning:
            skills.append(
                AgentSkill(
                    id="task-planning",
                    name="Task Planning",
                    description=f"Break down complex tasks into steps using {agent.name}",
                    tags=["planning"],
                    inputModes=["text"],
                    outputModes=["text"],
                )
            )

        # Calculate duration
        duration_ms = (time.time() - start_time) * 1000

        # Log successful well-known retrieval with current agent data
        log_a2a_operation(
            "well_known",
            agent_id,
            auth_context,
            status="completed",
            duration_ms=duration_ms,
            extra_metadata={
                "agent_name": agent.name,
                "agent_status": agent.status,
                "agent_description_length": len(agent.description) if agent.description else 0,
                "model_id": agent.model_id,
                "has_tools": bool(
                    agent.tools and isinstance(agent.tools, list) and len(agent.tools) > 0
                ),
                "has_planning": bool(agent.planning),
                "capabilities": ["streaming", "pushNotifications", "extendedAgentCard"],
                "skills_count": len(skills),
            },
        )

        from agentarea_common.utils.types import AgentProvider

        # Include current agent status and model information in description
        enhanced_description = (
            agent.description or f"AI agent powered by {agent.model_id or 'language model'}"
        )
        if agent.status and agent.status != "active":
            enhanced_description += f" (Status: {agent.status})"

        rpc_url = f"/api/v1/agents/{agent_id}/a2a/rpc"
        agent_card = AgentCard(
            name=agent.name,
            description=enhanced_description,
            supportedInterfaces=[
                AgentInterface(url=rpc_url, protocolBinding="JSONRPC", protocolVersion="1.0")
            ],
            version="1.0.0",
            provider=AgentProvider(organization="AgentArea", url=f"/api/v1/agents/{agent_id}"),
            documentationUrl=None,
            capabilities=capabilities,
            defaultInputModes=["text/plain", "application/json"],
            defaultOutputModes=["text/plain", "application/json"],
            skills=skills,
            securitySchemes=None,
        )
        return agent_card
    except A2AValidationError as e:
        duration_ms = (time.time() - start_time) * 1000
        log_a2a_operation(
            "well_known",
            agent_id,
            auth_context,
            status="failed",
            duration_ms=duration_ms,
            error=str(e),
        )
        if e.code == -32602:  # Agent not found
            raise HTTPException(status_code=404, detail=e.message) from e
        else:
            raise HTTPException(status_code=500, detail=e.message) from e
    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        log_a2a_operation(
            "well_known",
            agent_id,
            auth_context,
            status="failed",
            duration_ms=duration_ms,
            error=f"Failed to get agent discovery info: {e}",
        )
        raise HTTPException(
            status_code=500, detail=f"Failed to get agent discovery info: {e}"
        ) from e
