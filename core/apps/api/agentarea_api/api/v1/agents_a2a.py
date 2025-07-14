"""A2A Protocol endpoints for agent-specific communication.

This module provides A2A protocol-compliant JSON-RPC endpoints for individual agents.
Each agent has its own RPC endpoint at /v1/agents/{agent_id}/rpc
"""

import asyncio
import json
import logging
from typing import Any
from uuid import UUID, uuid4

from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentProvider,
    AgentSkill,
    CancelTaskRequest,
    CancelTaskResponse,
    DataPart,
    FileBase,
    FilePart,
    GetTaskRequest,
    GetTaskResponse,
    InternalError,
    InvalidRequestError,
    JSONRPCResponse,
    Message,
    MessageSendParams,
    MethodNotFoundError,
    SendMessageRequest,
    SendMessageResponse,
    SendStreamingMessageResponse,
    TaskIdParams,
    TaskQueryParams,
    TextPart,
)
from agentarea_agents.application.agent_service import AgentService
from agentarea_agents.domain.models import Agent
from agentarea_api.api.deps.services import TaskManagerDep, get_agent_service
from agentarea_api.api.v1.a2a_auth import (
    A2AAuthContext,
    allow_public_access,
    require_a2a_execute_auth,
    require_a2a_stream_auth,
)
from agentarea_tasks.task_manager import BaseTaskManager
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

# Create subrouter for A2A protocol endpoints
router = APIRouter()


@router.post("/rpc")
async def handle_agent_jsonrpc(
    agent_id: UUID,
    request: Request,
    task_manager: TaskManagerDep,
    auth_context: A2AAuthContext = Depends(require_a2a_execute_auth),
    agent_service: AgentService = Depends(get_agent_service),
) -> JSONRPCResponse:
    """A2A JSON-RPC endpoint for agent-specific communication.

    Handles all A2A protocol methods for a specific agent:
    - message/send
    - message/stream
    - tasks/get
    - tasks/cancel
    - agent/authenticatedExtendedCard
    """
    try:
        # Authentication is handled by auth_context dependency
        logger.info(f"A2A RPC request from user {auth_context.user_id} to agent {agent_id}")

        # Parse JSON-RPC request
        body = await request.json()
        logger.info(f"Received A2A JSON-RPC request for agent {agent_id}: {body.get('method')}")

        # Validate basic JSON-RPC structure
        if not isinstance(body, dict) or "method" not in body:
            return JSONRPCResponse(
                jsonrpc="2.0",
                id=body.get("id") if isinstance(body, dict) else None,
                result=None,
                error=InvalidRequestError(code=-32600, message="Invalid Request", data=None),
            )

        method = body.get("method")
        params = body.get("params", {})
        request_id = body.get("id", str(uuid4()))

        # Route to appropriate handler with agent context
        if method == "tasks/send":  # A2A standard method
            return await handle_task_send(request_id, params, task_manager, agent_id)
        elif method == "message/send":  # Legacy compatibility
            return await handle_message_send(request_id, params, task_manager, agent_id)
        elif method == "message/stream":
            # For streaming, we need to return SSE response directly
            return await handle_message_stream_sse(
                request, request_id, params, task_manager, agent_id
            )
        elif method == "tasks/get":
            return await handle_task_get(request_id, params, task_manager)
        elif method == "tasks/cancel":
            return await handle_task_cancel(request_id, params, task_manager)
        elif method == "agent/authenticatedExtendedCard":
            base_url = f"{request.url.scheme}://{request.url.netloc}"
            # Get agent from service
            agent = await agent_service.get(agent_id)
            return await handle_agent_card(request_id, params, agent, base_url)
        else:
            return JSONRPCResponse(id=request_id, error=MethodNotFoundError())

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in A2A JSON-RPC handler for agent {agent_id}: {e}", exc_info=True)
        return JSONRPCResponse(
            id=body.get("id") if "body" in locals() and isinstance(body, dict) else None,
            error=InternalError(message=str(e)),
        )


@router.get("/card")
async def get_agent_card(
    agent_id: UUID,
    request: Request,
    auth_context: A2AAuthContext = Depends(allow_public_access),
    agent_service: AgentService = Depends(get_agent_service),
) -> AgentCard:
    """Get A2A agent card for discovery."""
    agent = await agent_service.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    base_url = f"{request.url.scheme}://{request.url.netloc}"

    # Convert database agent to A2A AgentCard
    return AgentCard(
        name=agent.name,
        description=agent.description,
        url=f"{base_url}/v1/agents/{agent_id}/rpc",  # Agent-specific RPC endpoint
        version="1.0.0",
        documentation_url=f"{base_url}/v1/agents/{agent_id}/.well-known/a2a-info.json",
        capabilities=AgentCapabilities(
            streaming=True, push_notifications=False, state_transition_history=True
        ),
        provider=AgentProvider(organization="AgentArea"),
        skills=[
            AgentSkill(
                id="text-processing",
                name="Text Processing",
                description=f"Process and respond to text messages using {agent.name}",
                inputModes=["text"],
                outputModes=["text"],
            )
        ],
    )


# A2A JSON-RPC Method Handlers


async def handle_task_send(
    request_id: str,
    params: dict[str, Any],
    task_manager: BaseTaskManager,
    agent_id: UUID,
) -> SendMessageResponse:
    """Handle tasks/send RPC method (A2A standard method).

    This is the standard A2A method for sending tasks to agents.
    """
    try:
        # Extract task ID and message from params
        task_id = params.get("id", str(uuid4()))
        message_data = params.get("message", {})

        # Convert to A2A message format with support for all part types
        parts = []
        for part_data in message_data.get("parts", [{}]):
            part_type = part_data.get("type", "text")

            if part_type == "text":
                parts.append(
                    TextPart(text=part_data.get("text", ""), metadata=part_data.get("metadata"))
                )
            elif part_type == "file":
                file_data = part_data.get("file", {})
                parts.append(
                    FilePart(
                        file=FileBase(
                            name=file_data.get("name"),
                            mime_type=file_data.get("mime_type"),
                            bytes=file_data.get("bytes"),
                            uri=file_data.get("uri"),
                        ),
                        metadata=part_data.get("metadata"),
                    )
                )
            elif part_type == "data":
                parts.append(
                    DataPart(data=part_data.get("data", {}), metadata=part_data.get("metadata"))
                )
            else:
                # Fallback to text part for unknown types
                parts.append(TextPart(text=str(part_data), metadata=part_data.get("metadata")))

        message = Message(role=message_data.get("role", "user"), parts=parts)

        # Create task parameters with agent context
        task_params = MessageSendParams(
            id=task_id,
            session_id=params.get("sessionId", str(uuid4())),
            message=message,
            metadata={
                **params.get("metadata", {}),
                "agent_id": str(agent_id),
                "a2a_request": True,
                "method": "tasks/send",
            },
        )

        # Send task
        send_request = SendMessageRequest(id=request_id, params=task_params)
        response = await task_manager.on_send_message(send_request)

        return SendMessageResponse(id=request_id, result=response.result)

    except Exception as e:
        logger.error(f"Error in tasks/send for agent {agent_id}: {e}", exc_info=True)
        return SendMessageResponse(id=request_id, error=InternalError(message=str(e)))


async def handle_message_send(
    request_id: str,
    params: dict[str, Any],
    task_manager: BaseTaskManager,
    agent_id: UUID,
) -> SendMessageResponse:
    """Handle message/send RPC method for specific agent."""
    try:
        # Convert to A2A message format
        message = Message(
            role="user",
            parts=[TextPart(text=params.get("message", {}).get("parts", [{}])[0].get("text", ""))],
        )

        # Create task parameters with agent context
        task_params = MessageSendParams(
            id=str(uuid4()),
            session_id=params.get("contextId", str(uuid4())),
            message=message,
            metadata={
                **params.get("metadata", {}),
                "agent_id": str(agent_id),
                "a2a_request": True,
            },
        )

        # Send task
        send_request = SendMessageRequest(id=request_id, params=task_params)
        response = await task_manager.on_send_message(send_request)

        return SendMessageResponse(id=request_id, result=response.result)

    except Exception as e:
        logger.error(f"Error in message/send for agent {agent_id}: {e}", exc_info=True)
        return SendMessageResponse(id=request_id, error=InternalError(message=str(e)))


async def handle_message_stream_sse(
    request: Request,
    request_id: str,
    params: dict[str, Any],
    task_manager: BaseTaskManager,
    agent_id: UUID,
) -> StreamingResponse:
    """Handle message/stream RPC method with Server-Sent Events."""
    try:
        # Convert to A2A message format
        message_data = params.get("message", {})
        user_text = ""
        if message_data.get("parts"):
            user_text = message_data["parts"][0].get("text", "")

        message = Message(
            role="user",
            parts=[TextPart(text=user_text)],
        )

        # Create task parameters with agent context
        task_params = MessageSendParams(
            id=str(uuid4()),
            session_id=params.get("contextId", str(uuid4())),
            message=message,
            metadata={
                **params.get("metadata", {}),
                "agent_id": str(agent_id),
                "a2a_request": True,
                "streaming": True,
            },
        )

        async def stream_response():
            """Generate Server-Sent Events for A2A streaming."""
            try:
                # Send initial connection event as JSON-RPC response
                connection_event = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "type": "connection",
                        "status": "connected",
                        "taskId": task_params.id,
                        "sessionId": task_params.sessionId,
                        "kind": "connection",
                    },
                }
                yield f"data: {json.dumps(connection_event)}\n\n"

                # Send task to task manager
                send_request = SendMessageRequest(jsonrpc="2.0", id=request_id, params=task_params)
                response = await task_manager.on_send_message(send_request)

                if response.error:
                    # Send error event as JSON-RPC response
                    error_event = {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "error": {
                            "code": response.error.code,
                            "message": response.error.message,
                            "data": response.error.data,
                        },
                    }
                    yield f"data: {json.dumps(error_event)}\n\n"
                    return

                # Send task started event as TaskStatusUpdateEvent
                if response.result:
                    task_started_event = {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {
                            "taskId": response.result.id,
                            "sessionId": response.result.sessionId,
                            "status": {
                                "state": response.result.status.state,
                                "message": response.result.status.message,
                                "timestamp": response.result.status.timestamp.isoformat()
                                if response.result.status.timestamp
                                else None,
                            },
                            "final": False,
                            "kind": "status-update",
                        },
                    }
                    yield f"data: {json.dumps(task_started_event)}\n\n"

                # Poll for task completion and stream updates
                task_id = response.result.id if response.result else None
                if task_id:
                    max_attempts = 60  # 60 seconds timeout
                    for attempt in range(max_attempts):
                        # Get task status
                        get_request = GetTaskRequest(
                            jsonrpc="2.0",
                            id=f"{request_id}_poll_{attempt}",
                            params=TaskQueryParams(id=task_id),
                        )
                        task_response = await task_manager.on_get_task(get_request)

                        if task_response.result:
                            task = task_response.result

                            # Send status update as TaskStatusUpdateEvent
                            status_event = {
                                "jsonrpc": "2.0",
                                "id": request_id,
                                "result": {
                                    "taskId": task.id,
                                    "sessionId": task.sessionId,
                                    "status": {
                                        "state": task.status.state,
                                        "message": task.status.message,
                                        "timestamp": task.status.timestamp.isoformat()
                                        if task.status.timestamp
                                        else None,
                                    },
                                    "final": task.status.state
                                    in ["completed", "failed", "canceled"],
                                    "kind": "status-update",
                                },
                            }
                            yield f"data: {json.dumps(status_event)}\n\n"

                            # Send artifact updates if available
                            if task.artifacts:
                                for i, artifact in enumerate(task.artifacts):
                                    artifact_event = {
                                        "jsonrpc": "2.0",
                                        "id": request_id,
                                        "result": {
                                            "taskId": task.id,
                                            "sessionId": task.sessionId,
                                            "artifact": {
                                                "name": artifact.name,
                                                "description": artifact.description,
                                                "parts": [
                                                    part.model_dump() for part in artifact.parts
                                                ],
                                                "index": artifact.index,
                                                "append": artifact.append,
                                                "lastChunk": artifact.lastChunk,
                                                "metadata": artifact.metadata,
                                            },
                                            "kind": "artifact-update",
                                        },
                                    }
                                    yield f"data: {json.dumps(artifact_event)}\n\n"

                            # Check if task is complete
                            if task.status.state in ["completed", "failed", "canceled"]:
                                # Send final status event
                                final_event = {
                                    "jsonrpc": "2.0",
                                    "id": request_id,
                                    "result": {
                                        "taskId": task.id,
                                        "sessionId": task.sessionId,
                                        "status": {
                                            "state": task.status.state,
                                            "message": task.status.message,
                                            "timestamp": task.status.timestamp.isoformat()
                                            if task.status.timestamp
                                            else None,
                                        },
                                        "final": True,
                                        "kind": "status-update",
                                    },
                                }
                                yield f"data: {json.dumps(final_event)}\n\n"
                                break

                        # Wait before next poll
                        await asyncio.sleep(1)

                    else:
                        # Timeout reached
                        timeout_event = {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "error": {
                                "code": -32603,
                                "message": "Task polling timeout reached",
                                "data": {"timeout_seconds": 60},
                            },
                        }
                        yield f"data: {json.dumps(timeout_event)}\n\n"

            except Exception as e:
                logger.error(f"Error in SSE stream for agent {agent_id}: {e}", exc_info=True)
                error_event = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": -32603,
                        "message": "Internal error",
                        "data": {"details": str(e)},
                    },
                }
                yield f"data: {json.dumps(error_event)}\n\n"

        return StreamingResponse(
            stream_response(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "Cache-Control",
            },
        )

    except Exception as e:
        logger.error(f"Error setting up SSE stream for agent {agent_id}: {e}", exc_info=True)
        error_message = str(e)

        # Return error as SSE
        async def error_stream():
            error_data = {
                "type": "error",
                "id": request_id,
                "error": {"code": -32603, "message": f"Failed to setup stream: {error_message}"},
            }
            yield f"data: {json.dumps(error_data)}\n\n"

        return StreamingResponse(
            error_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "Cache-Control",
            },
        )


async def handle_message_stream(
    request_id: str,
    params: dict[str, Any],
    task_manager: BaseTaskManager,
    agent_id: UUID,
) -> SendStreamingMessageResponse:
    """Handle message/stream RPC method for specific agent (legacy)."""
    try:
        # For now, use the same logic as message/send
        # In production, this would set up SSE streaming with task manager
        message_response = await handle_message_send(request_id, params, task_manager, agent_id)
        return SendStreamingMessageResponse(
            id=request_id, result=message_response.result, error=message_response.error
        )
    except Exception as e:
        logger.error(f"Error in message/stream for agent {agent_id}: {e}", exc_info=True)
        return SendStreamingMessageResponse(id=request_id, error=InternalError(message=str(e)))


async def handle_task_get(
    request_id: str,
    params: dict[str, Any],
    task_manager: BaseTaskManager,
) -> GetTaskResponse:
    """Handle tasks/get RPC method."""
    try:
        get_request = GetTaskRequest(id=request_id, params=TaskQueryParams(id=params.get("id", "")))
        return await task_manager.on_get_task(get_request)
    except Exception as e:
        logger.error(f"Error in tasks/get: {e}", exc_info=True)
        return GetTaskResponse(id=request_id, error=InternalError(message=str(e)))


async def handle_task_cancel(
    request_id: str,
    params: dict[str, Any],
    task_manager: BaseTaskManager,
) -> CancelTaskResponse:
    """Handle tasks/cancel RPC method."""
    try:
        cancel_request = CancelTaskRequest(
            id=request_id, params=TaskIdParams(id=params.get("id", ""))
        )
        return await task_manager.on_cancel_task(cancel_request)
    except Exception as e:
        logger.error(f"Error in tasks/cancel: {e}", exc_info=True)
        return CancelTaskResponse(id=request_id, error=InternalError(message=str(e)))


async def handle_agent_card(
    request_id: str,
    params: dict[str, Any],
    agent: Agent,
    base_url: str,
) -> JSONRPCResponse:
    """Handle agent/authenticatedExtendedCard RPC method for specific agent."""
    # Convert database agent to A2A AgentCard
    agent_card = AgentCard(
        name=agent.name,
        description=agent.description,
        url=f"{base_url}/v1/agents/{agent.id}/rpc",
        version="1.0.0",
        documentation_url=f"{base_url}/v1/agents/{agent.id}/.well-known/a2a-info.json",
        capabilities=AgentCapabilities(
            streaming=True, push_notifications=False, state_transition_history=True
        ),
        provider=AgentProvider(organization="AgentArea"),
        skills=[
            AgentSkill(
                id="text-processing",
                name="Text Processing",
                description=f"Process and respond to text messages using {agent.name}",
                inputModes=["text"],
                outputModes=["text"],
            )
        ],
    )

    return JSONRPCResponse(id=request_id, result=agent_card)


@router.post("/stream")
async def stream_agent_communication(
    agent_id: UUID,
    request: Request,
    auth_context: A2AAuthContext = Depends(require_a2a_stream_auth),
) -> StreamingResponse:
    """Stream real-time communication with agent via Server-Sent Events.

    This endpoint provides A2A-compatible streaming for real-time agent interaction.
    """
    try:
        # Get agent info from auth context
        agent_name = auth_context.metadata.get("agent_name", f"Agent {agent_id}")

        # Parse JSON-RPC request from body
        body = await request.json()

        async def stream_response():
            """Generate Server-Sent Events for streaming response."""
            try:
                # Send initial connection event
                yield f"data: {json.dumps({'type': 'connection', 'status': 'connected', 'agent_id': str(agent_id)})}\n\n"

                # Process the request (simplified for now)
                if body.get("method") == "message/stream":
                    # Simulate streaming response
                    message_text = (
                        body.get("params", {})
                        .get("message", {})
                        .get("parts", [{}])[0]
                        .get("text", "")
                    )

                    # Stream response in chunks
                    response_text = f"{agent_name} received: {message_text}"
                    words = response_text.split()

                    for i, word in enumerate(words):
                        chunk_data = {
                            "type": "text_chunk",
                            "content": word + " ",
                            "chunk_index": i,
                            "total_chunks": len(words),
                            "agent_id": str(agent_id),
                        }
                        yield f"data: {json.dumps(chunk_data)}\n\n"
                        await asyncio.sleep(0.1)  # Simulate typing delay

                    # Send completion event
                    completion_data = {
                        "type": "completion",
                        "status": "completed",
                        "agent_id": str(agent_id),
                        "total_chunks": len(words),
                    }
                    yield f"data: {json.dumps(completion_data)}\n\n"

            except Exception as e:
                error_data = {"type": "error", "error": str(e), "agent_id": str(agent_id)}
                yield f"data: {json.dumps(error_data)}\n\n"

        return StreamingResponse(
            stream_response(),
            media_type="text/plain",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Content-Type": "text/event-stream",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "Cache-Control",
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in streaming endpoint for agent {agent_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Streaming failed")
