"""A2A Protocol endpoints for agent-specific communication.

This module provides A2A protocol-compliant JSON-RPC endpoints for individual agents.
Each agent has its own RPC endpoint at /v1/agents/{agent_id}/rpc
"""

import asyncio
import json
import logging
from typing import Any, AsyncGenerator
from uuid import UUID, uuid4

from agentarea_agents.application.agent_service import AgentService
from agentarea_agents.domain.models import Agent
from agentarea_api.api.deps.services import get_agent_service
from agentarea_api.api.v1.a2a_auth import (
    A2AAuthContext,
    allow_public_access,
    require_a2a_execute_auth,
    require_a2a_stream_auth,
)
from agentarea_common.utils.types import (
    AgentCapabilities,
    AgentCard,
    AgentProvider,
    AgentSkill,
    AuthenticatedExtendedCardResponse,
    CancelTaskRequest,
    CancelTaskResponse,
    DataPart,
    FilePart,
    FileContent,
    GetTaskRequest,
    GetTaskResponse,
    InternalError,
    InvalidRequestError,
    JSONRPCResponse,
    Message,
    MessageSendResponse,
    MessageStreamResponse,
    MethodNotFoundError,
    SendTaskRequest,
    TaskIdParams,
    TaskQueryParams,
    TaskSendParams,
    TextPart,
)
from agentarea_tasks.task_manager import BaseTaskManager
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Create subrouter for A2A protocol endpoints
router = APIRouter()


# Dependency injection for A2A protocol
async def get_task_manager() -> BaseTaskManager:
    """Get task manager instance for A2A protocol."""
    from agentarea_tasks.temporal_task_manager import TemporalTaskManager
    return TemporalTaskManager()


@router.post("/rpc")
async def handle_agent_jsonrpc(
    agent_id: UUID,
    request: Request,
    task_manager: BaseTaskManager = Depends(get_task_manager),
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
                id=body.get("id") if isinstance(body, dict) else None,
                error=InvalidRequestError()
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
            return await handle_message_stream(request_id, params, task_manager, agent_id)
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
            streaming=True,
            pushNotifications=False,
            stateTransitionHistory=True
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
) -> MessageSendResponse:
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
                parts.append(TextPart(
                    text=part_data.get("text", ""),
                    metadata=part_data.get("metadata")
                ))
            elif part_type == "file":
                file_data = part_data.get("file", {})
                parts.append(FilePart(
                    file=FileContent(
                        name=file_data.get("name"),
                        mime_type=file_data.get("mime_type"),
                        bytes=file_data.get("bytes"),
                        uri=file_data.get("uri")
                    ),
                    metadata=part_data.get("metadata")
                ))
            elif part_type == "data":
                parts.append(DataPart(
                    data=part_data.get("data", {}),
                    metadata=part_data.get("metadata")
                ))
            else:
                # Fallback to text part for unknown types
                parts.append(TextPart(
                    text=str(part_data),
                    metadata=part_data.get("metadata")
                ))
        
        message = Message(
            role=message_data.get("role", "user"),
            parts=parts
        )
        
        # Create task parameters with agent context
        task_params = TaskSendParams(
            id=task_id,
            sessionId=params.get("sessionId", str(uuid4())),
            message=message,
            metadata={
                **params.get("metadata", {}),
                "agent_id": str(agent_id),
                "a2a_request": True,
                "method": "tasks/send"
            },
        )
        
        # Send task
        send_request = SendTaskRequest(id=request_id, params=task_params)
        response = await task_manager.on_send_task(send_request)
        
        return MessageSendResponse(id=request_id, result=response.result)
    
    except Exception as e:
        logger.error(f"Error in tasks/send for agent {agent_id}: {e}", exc_info=True)
        return MessageSendResponse(id=request_id, error=InternalError(message=str(e)))


async def handle_message_send(
    request_id: str,
    params: dict[str, Any],
    task_manager: BaseTaskManager,
    agent_id: UUID,
) -> MessageSendResponse:
    """Handle message/send RPC method for specific agent."""
    try:
        # Convert to A2A message format
        message = Message(
            role="user",
            parts=[TextPart(text=params.get("message", {}).get("parts", [{}])[0].get("text", ""))],
        )
        
        # Create task parameters with agent context
        task_params = TaskSendParams(
            id=str(uuid4()),
            sessionId=params.get("contextId", str(uuid4())),
            message=message,
            metadata={
                **params.get("metadata", {}),
                "agent_id": str(agent_id),
                "a2a_request": True,
            },
        )
        
        # Send task
        send_request = SendTaskRequest(id=request_id, params=task_params)
        response = await task_manager.on_send_task(send_request)
        
        return MessageSendResponse(id=request_id, result=response.result)
    
    except Exception as e:
        logger.error(f"Error in message/send for agent {agent_id}: {e}", exc_info=True)
        return MessageSendResponse(id=request_id, error=InternalError(message=str(e)))


async def handle_message_stream(
    request_id: str,
    params: dict[str, Any],
    task_manager: BaseTaskManager,
    agent_id: UUID,
) -> MessageStreamResponse:
    """Handle message/stream RPC method for specific agent."""
    try:
        # For now, use the same logic as message/send
        # In production, this would set up SSE streaming with task manager
        message_response = await handle_message_send(request_id, params, task_manager, agent_id)
        return MessageStreamResponse(
            id=request_id,
            result=message_response.result,
            error=message_response.error
        )
    except Exception as e:
        logger.error(f"Error in message/stream for agent {agent_id}: {e}", exc_info=True)
        return MessageStreamResponse(id=request_id, error=InternalError(message=str(e)))


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
) -> AuthenticatedExtendedCardResponse:
    """Handle agent/authenticatedExtendedCard RPC method for specific agent."""
    # Convert database agent to A2A AgentCard
    agent_card = AgentCard(
        name=agent.name,
        description=agent.description,
        url=f"{base_url}/v1/agents/{agent.id}/rpc",
        version="1.0.0",
        documentation_url=f"{base_url}/v1/agents/{agent.id}/.well-known/a2a-info.json",
        capabilities=AgentCapabilities(
            streaming=True,
            pushNotifications=False,
            stateTransitionHistory=True
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
    
    return AuthenticatedExtendedCardResponse(id=request_id, result=agent_card)


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
                    message_text = body.get("params", {}).get("message", {}).get("parts", [{}])[0].get("text", "")
                    
                    # Stream response in chunks
                    response_text = f"{agent_name} received: {message_text}"
                    words = response_text.split()
                    
                    for i, word in enumerate(words):
                        chunk_data = {
                            "type": "text_chunk",
                            "content": word + " ",
                            "chunk_index": i,
                            "total_chunks": len(words),
                            "agent_id": str(agent_id)
                        }
                        yield f"data: {json.dumps(chunk_data)}\n\n"
                        await asyncio.sleep(0.1)  # Simulate typing delay
                    
                    # Send completion event
                    completion_data = {
                        "type": "completion",
                        "status": "completed",
                        "agent_id": str(agent_id),
                        "total_chunks": len(words)
                    }
                    yield f"data: {json.dumps(completion_data)}\n\n"
                
            except Exception as e:
                error_data = {
                    "type": "error",
                    "error": str(e),
                    "agent_id": str(agent_id)
                }
                yield f"data: {json.dumps(error_data)}\n\n"
        
        return StreamingResponse(
            stream_response(),
            media_type="text/plain",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Content-Type": "text/event-stream",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "Cache-Control"
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in streaming endpoint for agent {agent_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Streaming failed")