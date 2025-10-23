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
    get_event_stream_service,
    get_task_service,
)
from agentarea_api.api.v1.a2a_auth import (
    A2AAuthContext,
    allow_public_access,
    require_a2a_execute_auth,
)
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.context_manager import ContextManager
from agentarea_common.events.event_stream_service import EventStreamService
from agentarea_common.utils.types import (
    AgentCapabilities,
    AgentCard,
    AgentSkill,
    CancelTaskResponse,
    GetTaskResponse,
    JSONRPCError,
    JSONRPCRequest,
    JSONRPCResponse,
    Message,
    MessageSendParams,
    TextPart,
)
from agentarea_common.utils.types import (
    AuthenticatedExtendedCardResponse as AgentAuthenticatedExtendedCardResponse,
)
from agentarea_common.utils.types import (
    MessageSendResponse as SendMessageResponse,
)
from agentarea_tasks.domain.models import SimpleTask
from agentarea_tasks.task_service import TaskService
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
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
    """
    # Extract user context from A2A auth
    if auth_context.authenticated and auth_context.user_id:
        user_id = auth_context.user_id
        workspace_id = auth_context.workspace_id or "default"
    else:
        # For unauthenticated A2A requests, use system defaults
        user_id = "a2a_anonymous"
        workspace_id = "default"

    # Create UserContext for repository layer
    user_context = UserContext(
        user_id=user_id,
        workspace_id=workspace_id,
        roles=[],  # A2A doesn't use roles, use permissions instead
    )

    # Set context in ContextManager so repositories can access it
    ContextManager.set_context(user_context)

    logger.debug(
        f"Set user context for A2A request: user_id={user_id}, workspace_id={workspace_id}"
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
        raise A2AValidationError(f"Failed to validate agent availability: {e}", -32603)


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
        raise A2AValidationError(f"Invalid message parameters: {'; '.join(error_details)}", -32602)
    except Exception as e:
        raise A2AValidationError(f"Failed to parse message parameters: {e}", -32602)


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
    except ValueError:
        raise A2AValidationError(f"Invalid task ID format: {task_id_str}", -32602)


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
) -> SimpleTask:
    """Convert A2A message to SimpleTask with proper authentication context and user metadata."""
    message_content = ""
    if message_params.message and message_params.message.parts:
        for part in message_params.message.parts:
            if hasattr(part, "text"):
                message_content += part.text

    # Extract proper user context from authentication
    # Note: The user context should already be set in ContextManager by set_user_context_from_a2a_auth()
    if auth_context.authenticated and auth_context.user_id:
        user_id = auth_context.user_id
        workspace_id = auth_context.workspace_id or "default"
    else:
        # For unauthenticated requests, use system defaults
        user_id = "a2a_anonymous"
        workspace_id = "default"

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
            "is_streaming": a2a_method == "message/stream",
            "agent_target": str(agent_id),
        },
    }
    # Merge any provided metadata from A2A params (e.g., requires_human_approval)
    if getattr(message_params, "metadata", None):
        try:
            a2a_metadata.update(message_params.metadata)
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

    return SimpleTask(
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


def convert_simple_task_to_a2a_task(task: SimpleTask):
    """Convert SimpleTask to A2A protocol Task format with current workflow status."""
    from agentarea_common.utils.types import Task, TaskState, TaskStatus

    # Map SimpleTask status to TaskState enum
    task_state_mapping = {
        "submitted": TaskState.SUBMITTED,
        "running": TaskState.WORKING,
        "working": TaskState.WORKING,
        "completed": TaskState.COMPLETED,
        "failed": TaskState.FAILED,
        "cancelled": TaskState.CANCELED,  # Note: A2A protocol uses "canceled" (one 'l')
        "canceled": TaskState.CANCELED,
    }

    task_state = task_state_mapping.get(task.status, TaskState.SUBMITTED)
    task_status = TaskStatus(state=task_state, message=None)

    return Task(
        id=str(task.id),
        session_id=None,
        status=task_status,
        artifacts=None,
        history=None,
        metadata=task.metadata or {},
    )


async def handle_task_send(request_id, params, task_service, agent_id, auth_context, agent_service):
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
            message_send_params, agent_id, auth_context, "tasks/send", request_id
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

        # Create A2A protocol-compliant Task response
        from agentarea_common.utils.types import Task, TaskState, TaskStatus

        task_status = TaskStatus(state=TaskState.SUBMITTED, message=None)

        a2a_task = Task(
            id=str(created_task.id),
            session_id=None,
            status=task_status,
            artifacts=None,
            history=None,
            metadata=created_task.metadata,
        )

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
    request_id, params, task_service, agent_id, auth_context, agent_service
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
        message = Message(role="user", parts=[TextPart(text=text_content)])
        # Include optional metadata from params (e.g., requires_human_approval)
        message_params = MessageSendParams(message=message, metadata=params.get("metadata"))

        # Convert to task with proper metadata
        task = convert_a2a_message_to_task(
            message_params, agent_id, auth_context, "message/send", request_id
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

        # Create A2A protocol-compliant Task response
        from agentarea_common.utils.types import Task, TaskState, TaskStatus

        task_status = TaskStatus(state=TaskState.SUBMITTED, message=None)

        a2a_task = Task(
            id=str(created_task.id),
            session_id=None,
            status=task_status,
            artifacts=None,
            history=None,
            metadata=created_task.metadata,
        )

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
    request, request_id, params, task_service, agent_id, auth_context, agent_service, event_stream_service
):
    """Handle A2A message/stream method with proper TaskService integration, validation, and real event streaming."""
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
        message = Message(role="user", parts=[TextPart(text=text_content)])
        # Include optional metadata from params (e.g., requires_human_approval)
        message_params = MessageSendParams(message=message, metadata=params.get("metadata"))

        # Create task with proper A2A metadata
        task = convert_a2a_message_to_task(
            message_params,
            agent_id,
            auth_context,
            "message/stream",
            request_id,
            params.get("id"),  # Use provided task ID if available
        )

        # Submit task through TaskService - this ensures Temporal workflow execution
        created_task = await task_service.submit_task(task)

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

        async def event_stream():
            """Stream real task events using TaskService.stream_task_events()."""
            event_count = 0
            stream_start_time = time.time()

            try:
                # Send initial task created event with timestamp
                from datetime import UTC, datetime

                initial_event = {
                    "event": "task_created",
                    "task_id": str(created_task.id),
                    "status": created_task.status,
                    "timestamp": datetime.now(UTC).isoformat(),
                    "data": {
                        "task_id": str(created_task.id),
                        "agent_id": str(agent_id),
                        "status": created_task.status,
                        "a2a_metadata": {
                            "source": "a2a",
                            "method": "message/stream",
                            "request_id": request_id,
                        },
                    },
                }
                yield f"data: {json.dumps(initial_event)}\n\n"
                event_count += 1

                # Stream real events from EventStreamService
                async for event in event_stream_service.stream_events_for_task(
                    created_task.id, event_patterns=["workflow.*"]
                ):
                    event_count += 1

                    # Format event for A2A protocol SSE response
                    event_type = event.get("event_type", "unknown")
                    # Strip "workflow." prefix if present
                    if event_type.startswith("workflow."):
                        event_type = event_type[9:]

                    # Add A2A-specific metadata to event data
                    event_data = event.get("data", {})
                    event_data["a2a_metadata"] = {
                        "source": "a2a",
                        "method": "message/stream",
                        "request_id": request_id,
                        "event_sequence": event_count,
                    }

                    a2a_event = {
                        "event": event_type,
                        "task_id": str(created_task.id),
                        "timestamp": event.get("timestamp"),
                        "data": event_data,
                    }

                    yield f"data: {json.dumps(a2a_event)}\n\n"

                    # Check if task is completed (check both with and without prefix)
                    if event_type in [
                        "task_completed",
                        "task_failed",
                        "task_cancelled",
                    ] or event.get("event_type") in [
                        "workflow.task_completed",
                        "workflow.task_failed",
                        "workflow.task_cancelled",
                    ]:
                        break

                # Send completion marker
                yield "data: [DONE]\n\n"

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
                    extra_metadata={
                        "events_streamed": event_count,
                        "stream_duration_ms": stream_duration_ms,
                    },
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
                    extra_metadata={
                        "events_streamed": event_count,
                        "stream_duration_ms": stream_duration_ms,
                    },
                )
                yield f"data: {json.dumps({'event': 'error', 'code': -32603, 'message': str(stream_error)})}\n\n"

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

        async def error_stream():
            yield f"data: {json.dumps({'event': 'error', 'code': e.code, 'message': e.message})}\n\n"  # noqa: F821

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

        async def error_stream():
            yield f"data: {json.dumps({'event': 'error', 'code': e.code, 'message': e.message})}\n\n"  # noqa: F821

        return StreamingResponse(error_stream(), media_type="text/event-stream")
    except ValueError as e:
        # Handle TaskService validation errors (e.g., agent not found in TaskService)
        duration_ms = (time.time() - start_time) * 1000
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
            yield f"data: {json.dumps({'event': 'error', 'code': -32602, 'message': f'Invalid parameters: {e}'})}\n\n"  # noqa: F821

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

        # Convert SimpleTask to A2A protocol Task format
        a2a_task = convert_simple_task_to_a2a_task(task)

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
            a2a_task = convert_simple_task_to_a2a_task(updated_task)

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


async def handle_agent_card(request_id, params, agent_service, agent_id, base_url, auth_context):
    """Handle A2A agent/authenticatedExtendedCard method with current agent data and proper validation."""
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
            push_notifications=False,  # Not currently supported
            state_transition_history=True,  # Supported through Temporal workflows
        )

        # Build skills based on agent configuration and tools
        skills = []

        # Base text processing skill for all agents
        skills.append(
            AgentSkill(
                id="text-processing",
                name="Text Processing",
                description=f"Process and respond to text messages using {agent.name}",
                input_modes=["text"],
                output_modes=["text"],
            )
        )

        # Add tool-based skills if agent has tools configured
        if agent.tools_config and isinstance(agent.tools_config, dict):
            tools_list = agent.tools_config.get("tools", [])
            if tools_list:
                skills.append(
                    AgentSkill(
                        id="tool-execution",
                        name="Tool Execution",
                        description=f"Execute tools and integrations using {agent.name}",
                        input_modes=["text"],
                        output_modes=["text", "data"],
                    )
                )

        # Add planning skill if agent has planning enabled
        if agent.planning:
            skills.append(
                AgentSkill(
                    id="task-planning",
                    name="Task Planning",
                    description=f"Break down complex tasks into steps using {agent.name}",
                    input_modes=["text"],
                    output_modes=["text"],
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
                "has_tools": bool(agent.tools_config and agent.tools_config.get("tools")),
                "has_planning": bool(agent.planning),
                "skills_count": len(skills),
                "base_url": base_url,
                "capabilities": ["streaming", "state_transition_history"],
            },
        )

        from agentarea_common.utils.types import AgentProvider

        # Include current agent status and model information in description
        enhanced_description = (
            agent.description or f"AI agent powered by {agent.model_id or 'language model'}"
        )
        if agent.status and agent.status != "active":
            enhanced_description += f" (Status: {agent.status})"

        agent_card = AgentCard(
            name=agent.name,
            description=enhanced_description,
            url=f"{base_url}/api/v1/agents/{agent_id}/a2a/rpc",
            version="1.0.0",
            provider=AgentProvider(
                organization="AgentArea", url=f"{base_url}/api/v1/agents/{agent_id}"
            ),
            capabilities=capabilities,
            skills=skills,
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
    event_stream_service,
):
    """Dispatch A2A RPC method calls with proper error handling."""
    base_url = f"{request.url.scheme}://{request.url.netloc}" if request else None
    handlers = {
        "tasks/send": lambda: handle_task_send(
            request_id, params, task_service, agent_id, auth_context, agent_service
        ),
        "message/send": lambda: handle_message_send(
            request_id, params, task_service, agent_id, auth_context, agent_service
        ),
        "message/stream": lambda: handle_message_stream_sse(
            request, request_id, params, task_service, agent_id, auth_context, agent_service, event_stream_service
        ),
        "tasks/get": lambda: handle_task_get(
            request_id, params, task_service, agent_id, auth_context
        ),
        "tasks/cancel": lambda: handle_task_cancel(
            request_id, params, task_service, agent_id, auth_context
        ),
        "agent/authenticatedExtendedCard": lambda: handle_agent_card(
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


@router.post("/rpc")
async def handle_agent_jsonrpc(
    agent_id: UUID,
    request: Request,
    auth_context: A2AAuthContext = Depends(require_a2a_execute_auth),
    task_service: TaskService = Depends(get_task_service),
    agent_service: AgentService = Depends(get_agent_service),
    event_stream_service: EventStreamService = Depends(get_event_stream_service),
) -> JSONRPCResponse:
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

        # Set user context from A2A auth for repository layer (for methods that don't set it themselves)
        if method not in ["tasks/send", "message/send", "message/stream"]:
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
            event_stream_service=event_stream_service,
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
                "is_streaming_response": hasattr(result, "media_type")
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
            push_notifications=False,  # Not currently supported
            state_transition_history=True,  # Supported through Temporal workflows
        )

        # Build skills based on current agent configuration and tools
        skills = []

        # Base text processing skill for all agents
        skills.append(
            AgentSkill(
                id="text-processing",
                name="Text Processing",
                description=f"Process and respond to text messages using {agent.name}",
                input_modes=["text"],
                output_modes=["text"],
            )
        )

        # Add tool-based skills if agent has tools configured
        if agent.tools_config and isinstance(agent.tools_config, dict):
            tools_list = agent.tools_config.get("tools", [])
            if tools_list:
                skills.append(
                    AgentSkill(
                        id="tool-execution",
                        name="Tool Execution",
                        description=f"Execute tools and integrations using {agent.name}",
                        input_modes=["text"],
                        output_modes=["text", "data"],
                    )
                )

        # Add planning skill if agent has planning enabled
        if agent.planning:
            skills.append(
                AgentSkill(
                    id="task-planning",
                    name="Task Planning",
                    description=f"Break down complex tasks into steps using {agent.name}",
                    input_modes=["text"],
                    output_modes=["text"],
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
                "has_tools": bool(agent.tools_config and agent.tools_config.get("tools")),
                "has_planning": bool(agent.planning),
                "capabilities": ["streaming", "state_transition_history"],
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

        agent_card = AgentCard(
            name=agent.name,
            description=enhanced_description,
            url=f"/api/v1/agents/{agent_id}/a2a/rpc",
            version="1.0.0",
            provider=AgentProvider(organization="AgentArea", url=f"/api/v1/agents/{agent_id}"),
            capabilities=capabilities,
            skills=skills,
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
            raise HTTPException(status_code=404, detail=e.message)
        else:
            raise HTTPException(status_code=500, detail=e.message)
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
        raise HTTPException(status_code=500, detail=f"Failed to get agent discovery info: {e}")
