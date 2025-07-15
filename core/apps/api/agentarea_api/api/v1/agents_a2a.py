"""A2A (Agent-to-Agent) protocol endpoints for AgentArea.

This module implements the A2A protocol for inter-agent communication.
The A2A protocol is a JSON-RPC based protocol that allows agents to:
- Send messages to other agents
- Submit tasks for execution
- Query task status
- Cancel tasks

Key endpoints:
- POST /agents/{agent_id}/a2a/rpc - JSON-RPC endpoint for A2A protocol
- GET /agents/{agent_id}/a2a/well-known - Agent discovery endpoint
"""

import json
import logging
from typing import Any, AsyncGenerator, Dict, List, Optional
from uuid import UUID, uuid4

from agentarea_common.utils.types import (
    AgentCard,
    AgentCapabilities,
    AuthenticatedExtendedCardResponse as AgentAuthenticatedExtendedCardResponse,
    CancelTaskRequest,
    CancelTaskResponse,
    GetTaskRequest,
    GetTaskResponse,
    JSONRPCRequest,
    JSONRPCResponse,
    Message,
    MessageSendParams,
    MessageSendResponse as SendMessageResponse,
    MessageStreamResponse as SendStreamingMessageResponse,
    TaskIdParams,
    TaskQueryParams,
    TaskStatus,
    TextPart,
)
from agentarea_agents.application.agent_service import AgentService
from agentarea_api.api.deps.services import get_agent_service, get_task_service
from agentarea_api.api.v1.a2a_auth import (
    A2AAuthContext,
    allow_public_access,
    require_a2a_execute_auth,
    require_a2a_stream_auth,
)
from agentarea_tasks.task_service import TaskService
from agentarea_tasks.domain.models import SimpleTask
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

# Create subrouter for A2A protocol endpoints
router = APIRouter()


@router.post("/rpc")
async def handle_agent_jsonrpc(
    agent_id: UUID,
    request: Request,
    task_service: TaskService = Depends(get_task_service),
    auth_context: A2AAuthContext = Depends(require_a2a_execute_auth),
    agent_service: AgentService = Depends(get_agent_service),
) -> JSONRPCResponse:
    """A2A JSON-RPC endpoint for agent-specific communication.

    Handles all A2A protocol methods for a specific agent:
    - message/send
    - message/stream
    - tasks/get
    - tasks/cancel
    - tasks/send
    - agent/authenticatedExtendedCard
    """
    try:
        # Parse JSON-RPC request
        body = await request.body()
        request_data = json.loads(body)
        rpc_request = JSONRPCRequest(**request_data)
        
        method = rpc_request.method
        params = rpc_request.params or {}
        request_id = rpc_request.id

        logger.info(f"A2A RPC call: {method} for agent {agent_id}")

        # Route to appropriate handler with agent context
        if method == "tasks/send":  # A2A standard method
            return await handle_task_send(request_id, params, task_service, agent_id)
        elif method == "message/send":  # Legacy compatibility
            return await handle_message_send(request_id, params, task_service, agent_id)
        elif method == "message/stream":
            # For streaming, we need to return SSE response directly
            return await handle_message_stream_sse(
                request, request_id, params, task_service, agent_id
            )
        elif method == "tasks/get":
            return await handle_task_get(request_id, params, task_service)
        elif method == "tasks/cancel":
            return await handle_task_cancel(request_id, params, task_service)
        elif method == "agent/authenticatedExtendedCard":
            base_url = f"{request.url.scheme}://{request.url.netloc}"
            return await handle_agent_card(
                request_id, params, agent_service, agent_id, base_url
            )
        else:
            return JSONRPCResponse(
                jsonrpc="2.0",
                id=request_id,
                error={"code": -32601, "message": f"Method not found: {method}"},
            )

    except json.JSONDecodeError:
        return JSONRPCResponse(
            jsonrpc="2.0",
            id=None,
            error={"code": -32700, "message": "Parse error"},
        )
    except Exception as e:
        logger.error(f"A2A RPC error: {e}")
        return JSONRPCResponse(
            jsonrpc="2.0",
            id=request_id if 'request_id' in locals() else None,
            error={"code": -32603, "message": f"Internal error: {str(e)}"},
        )


# A2A Protocol Helper Functions

def convert_a2a_message_to_task(message_params: MessageSendParams, agent_id: UUID) -> SimpleTask:
    """Convert A2A message parameters to internal SimpleTask format."""
    # Extract message content
    message_content = ""
    if message_params.message and message_params.message.parts:
        for part in message_params.message.parts:
            if hasattr(part, 'text'):
                message_content += part.text
    
    # Create task from A2A message
    task = SimpleTask(
        id=UUID(message_params.id) if message_params.id else uuid4(),
        title=f"A2A Message Task",
        description=f"Task created from A2A message",
        query=message_content,
        user_id="a2a_user",  # A2A requests don't have user context
        agent_id=agent_id,
        status="submitted",
        task_parameters={}
    )
    return task


def convert_task_to_a2a_response(task: SimpleTask) -> Dict[str, Any]:
    """Convert internal task to A2A response format."""
    return {
        "id": str(task.id),
        "status": task.status,
        "result": task.result,
        "error": task.error_message,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
    }


# A2A Protocol Handler Functions

async def handle_task_send(
    request_id: str,
    params: dict[str, Any],
    task_service: TaskService,
    agent_id: UUID,
) -> SendMessageResponse:
    """Handle tasks/send RPC method (A2A standard method)."""
    try:
        # Convert params to MessageSendParams
        message_send_params = MessageSendParams(**params)
        
        # Convert A2A message to internal task
        task = convert_a2a_message_to_task(message_send_params, agent_id)
        
        # Submit task through task service
        created_task = await task_service.submit_task(task)
        
        # Return A2A response
        return SendMessageResponse(
            jsonrpc="2.0",
            id=request_id,
            result={
                "id": str(created_task.id),
                "status": created_task.status,
                "message": "Task submitted successfully"
            }
        )
    
    except Exception as e:
        logger.error(f"Error in handle_task_send: {e}")
        return SendMessageResponse(
            jsonrpc="2.0",
            id=request_id,
            error={"code": -32603, "message": f"Task submission failed: {str(e)}"}
        )


async def handle_message_send(
    request_id: str,
    params: dict[str, Any],
    task_service: TaskService,
    agent_id: UUID,
) -> SendMessageResponse:
    """Handle message/send RPC method (legacy compatibility)."""
    try:
        # Convert legacy message format to A2A format
        message_data = params.get("message", {})
        parts = message_data.get("parts", [])
        
        # Extract text from parts
        text_content = ""
        for part in parts:
            if isinstance(part, dict) and "text" in part:
                text_content += part["text"]
        
        # Create A2A message format
        message = Message(
            role="user",
            parts=[TextPart(text=text_content)]
        )
        
        # Create MessageSendParams
        message_params = MessageSendParams(
            id=params.get("id", str(uuid4())),
            message=message
        )
        
        # Use the same logic as handle_task_send
        return await handle_task_send(request_id, message_params.dict(), task_service, agent_id)

    except Exception as e:
        logger.error(f"Error in handle_message_send: {e}")
        return SendMessageResponse(
            jsonrpc="2.0",
            id=request_id,
            error={"code": -32603, "message": f"Message send failed: {str(e)}"}
        )


async def handle_message_stream_sse(
    request: Request,
    request_id: str,
    params: dict[str, Any],
    task_service: TaskService,
    agent_id: UUID,
) -> StreamingResponse:
    """Handle message/stream RPC method with Server-Sent Events."""
    try:
        # Convert to A2A message format
        message_data = params.get("message", {})
        parts = message_data.get("parts", [])
        
        # Extract text from parts
        text_content = ""
        for part in parts:
            if isinstance(part, dict) and "text" in part:
                text_content += part["text"]
        
        # Create task from message
        task = SimpleTask(
            id=UUID(params.get("id", str(uuid4()))),
            title="A2A Stream Task",
            description="Task created from A2A stream message",
            query=text_content,
            user_id="a2a_user",
            agent_id=agent_id,
            status="submitted",
            task_parameters={}
        )
        
        # Submit task
        created_task = await task_service.submit_task(task)
        
        # Create SSE stream
        async def event_stream():
            # Send initial response
            yield f"data: {json.dumps({'event': 'task_created', 'task_id': str(created_task.id)})}\n\n"
            
            # For now, just send a completion event
            # In a real implementation, this would stream events from the task execution
            yield f"data: {json.dumps({'event': 'task_completed', 'task_id': str(created_task.id), 'result': created_task.result})}\n\n"
            
            # Send end event
            yield f"data: [DONE]\n\n"

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Access-Control-Allow-Origin": "*",
            }
        )

    except Exception as e:
        logger.error(f"Error in handle_message_stream_sse: {e}")

        async def error_stream():
            yield f"data: {json.dumps({'event': 'error', 'message': str(e)})}\n\n"

        return StreamingResponse(
            error_stream(),
            media_type="text/event-stream"
        )


async def handle_message_stream(
    request_id: str,
    params: dict[str, Any],
    task_service: TaskService,
    agent_id: UUID,
) -> SendStreamingMessageResponse:
    """Handle message/stream RPC method (legacy)."""
    try:
        # For now, use the same logic as message/send
        message_response = await handle_message_send(request_id, params, task_service, agent_id)
        return SendStreamingMessageResponse(
            jsonrpc="2.0",
            id=request_id,
            result=message_response.result if hasattr(message_response, 'result') else {},
        )
    except Exception as e:
        logger.error(f"Error in handle_message_stream: {e}")
        return SendStreamingMessageResponse(
            jsonrpc="2.0",
            id=request_id,
            error={"code": -32603, "message": f"Stream failed: {str(e)}"}
        )


async def handle_task_get(
    request_id: str,
    params: dict[str, Any],
    task_service: TaskService,
) -> GetTaskResponse:
    """Handle tasks/get RPC method."""
    try:
        task_id = UUID(params.get("id", ""))
        task = await task_service.get_task(task_id)
        
        if not task:
            return GetTaskResponse(
                jsonrpc="2.0",
                id=request_id,
                error={"code": -32602, "message": f"Task not found: {task_id}"}
            )
        
        return GetTaskResponse(
            jsonrpc="2.0",
            id=request_id,
            result=convert_task_to_a2a_response(task)
        )
    
    except Exception as e:
        logger.error(f"Error in handle_task_get: {e}")
        return GetTaskResponse(
            jsonrpc="2.0",
            id=request_id,
            error={"code": -32603, "message": f"Task get failed: {str(e)}"}
        )


async def handle_task_cancel(
    request_id: str,
    params: dict[str, Any],
    task_service: TaskService,
) -> CancelTaskResponse:
    """Handle tasks/cancel RPC method."""
    try:
        task_id = UUID(params.get("id", ""))
        success = await task_service.cancel_task(task_id)
        
        return CancelTaskResponse(
            jsonrpc="2.0",
            id=request_id,
            result={"success": success, "message": "Task cancelled" if success else "Task not found or already completed"}
        )
    
    except Exception as e:
        logger.error(f"Error in handle_task_cancel: {e}")
        return CancelTaskResponse(
            jsonrpc="2.0",
            id=request_id,
            error={"code": -32603, "message": f"Task cancel failed: {str(e)}"}
        )


async def handle_agent_card(
    request_id: str,
    params: dict[str, Any],
    agent_service: AgentService,
    agent_id: UUID,
    base_url: str,
) -> AgentAuthenticatedExtendedCardResponse:
    """Handle agent/authenticatedExtendedCard RPC method."""
    try:
        # Get agent from service
        agent = await agent_service.get_agent(agent_id)
        if not agent:
            return AgentAuthenticatedExtendedCardResponse(
                jsonrpc="2.0",
                id=request_id,
                error={"code": -32602, "message": f"Agent not found: {agent_id}"}
            )
        
        # Create A2A agent card
        agent_card = AgentCard(
            id=str(agent.id),
            name=agent.name,
            description=agent.description or "",
            capabilities=AgentCapabilities(
                can_send_messages=True,
                can_receive_messages=True,
                can_execute_tasks=True,
                supports_streaming=True,
            ),
            endpoints={
                "a2a_rpc": f"{base_url}/api/v1/agents/{agent_id}/a2a/rpc",
                "well_known": f"{base_url}/api/v1/agents/{agent_id}/a2a/well-known",
            },
        )
        
        return AgentAuthenticatedExtendedCardResponse(
            jsonrpc="2.0",
            id=request_id,
            result=agent_card
        )
    
    except Exception as e:
        logger.error(f"Error in handle_agent_card: {e}")
        return AgentAuthenticatedExtendedCardResponse(
            jsonrpc="2.0",
            id=request_id,
            error={"code": -32603, "message": f"Agent card failed: {str(e)}"}
        )


@router.get("/well-known")
async def get_agent_well_known(
    agent_id: UUID,
    auth_context: A2AAuthContext = Depends(allow_public_access),
    agent_service: AgentService = Depends(get_agent_service),
) -> AgentCard:
    """Get agent well-known information (public endpoint)."""
    try:
        # Get agent from service
        agent = await agent_service.get_agent(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")
        
        # Create A2A agent card
        agent_card = AgentCard(
            id=str(agent.id),
            name=agent.name,
            description=agent.description or "",
            capabilities=AgentCapabilities(
                can_send_messages=True,
                can_receive_messages=True,
                can_execute_tasks=True,
                supports_streaming=True,
            ),
            endpoints={
                "a2a_rpc": f"/api/v1/agents/{agent_id}/a2a/rpc",
                "well_known": f"/api/v1/agents/{agent_id}/a2a/well-known",
            },
        )
        
        return agent_card
    
    except Exception as e:
        logger.error(f"Error in get_agent_well_known: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get agent info: {str(e)}")
