"""Agent Protocol API Endpoints

This module provides A2A protocol-compliant JSON-RPC endpoints for agent communication.
Focused on A2A protocol compliance - use /v1/agents/{agent_id}/tasks/ for REST task operations.
"""

import logging
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request

from agentarea.api.deps.services import get_agent_service
from agentarea.common.utils.types import (
    AgentCapabilities,
    AgentCard,
    AgentProvider,
    AgentSkill,
    AuthenticatedExtendedCardResponse,
    CancelTaskRequest,
    CancelTaskResponse,
    GetTaskRequest,
    GetTaskResponse,
    InternalError,
    InvalidRequestError,
    # Error types
    JSONRPCResponse,
    # Core types
    Message,
    # A2A Protocol types
    MessageSendResponse,
    MessageStreamResponse,
    MethodNotFoundError,
    SendTaskRequest,
    TaskIdParams,
    TaskQueryParams,
    TaskSendParams,
    TextPart,
)
from agentarea.modules.agents.application.agent_service import AgentService
from agentarea.modules.tasks.in_memory_task_manager import InMemoryTaskManager
from agentarea.modules.tasks.task_manager import BaseTaskManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/protocol", tags=["protocol"])


# Dependency injection
async def get_task_manager() -> BaseTaskManager:
    """Get task manager instance."""
    return InMemoryTaskManager()


# Real agent registry using database
async def get_agent_card_by_id(
    agent_id: str, agent_service: AgentService = Depends(get_agent_service)
) -> AgentCard | None:
    """Get agent card from database by ID."""
    try:
        # Try to parse as UUID
        agent_uuid = UUID(agent_id)
        agent = await agent_service.get(agent_uuid)

        if not agent:
            return None

        # Convert database agent to A2A AgentCard
        return AgentCard(
            name=agent.name,
            description=agent.description,
            url="http://localhost:8000/v1/protocol",
            version="1.0.0",
            capabilities=AgentCapabilities(
                streaming=True, pushNotifications=False, stateTransitionHistory=True
            ),
            provider=AgentProvider(organization="AgentArea"),
            skills=[
                AgentSkill(
                    id="text-processing",
                    name="Text Processing",
                    description="Process and respond to text messages using " + agent.name,
                    inputModes=["text"],
                    outputModes=["text"],
                )
            ],
        )
    except (ValueError, TypeError):
        # If not a valid UUID, try the demo agent fallback
        if agent_id == "demo-agent":
            return AgentCard(
                name="Demo Agent",
                description="A demonstration agent for testing A2A protocol",
                url="http://localhost:8000/v1/protocol",
                version="1.0.0",
                capabilities=AgentCapabilities(
                    streaming=True, pushNotifications=False, stateTransitionHistory=True
                ),
                provider=AgentProvider(organization="AgentArea Demo"),
                skills=[
                    AgentSkill(
                        id="text-processing",
                        name="Text Processing",
                        description="Process and respond to text messages",
                        inputModes=["text"],
                        outputModes=["text"],
                    )
                ],
            )
        return None


# A2A JSON-RPC Endpoint
@router.post("/rpc")
async def handle_jsonrpc(
    request: Request, task_manager: BaseTaskManager = Depends(get_task_manager)
) -> JSONRPCResponse:
    """Unified A2A JSON-RPC endpoint.

    Handles all A2A protocol methods:
    - message/send
    - message/stream
    - tasks/get
    - tasks/cancel
    - agent/authenticatedExtendedCard
    """
    try:
        # Parse JSON-RPC request
        body = await request.json()
        logger.info(f"Received JSON-RPC request: {body.get('method')}")

        # Validate basic JSON-RPC structure
        if not isinstance(body, dict) or "method" not in body:
            return JSONRPCResponse(
                id=body.get("id") if isinstance(body, dict) else None, error=InvalidRequestError()
            )

        method = body.get("method")
        params = body.get("params", {})
        request_id = body.get("id", str(uuid4()))

        # Route to appropriate handler
        if method == "message/send":
            return await handle_message_send(request_id, params, task_manager)
        elif method == "message/stream":
            return await handle_message_stream(request_id, params, task_manager)
        elif method == "tasks/get":
            return await handle_task_get(request_id, params, task_manager)
        elif method == "tasks/cancel":
            return await handle_task_cancel(request_id, params, task_manager)
        elif method == "agent/authenticatedExtendedCard":
            return await handle_agent_card(request_id, params)
        else:
            return JSONRPCResponse(id=request_id, error=MethodNotFoundError())

    except Exception as e:
        logger.error(f"Error in JSON-RPC handler: {e}", exc_info=True)
        return JSONRPCResponse(
            id=body.get("id") if "body" in locals() and isinstance(body, dict) else None,
            error=InternalError(message=str(e)),
        )


# JSON-RPC Method Handlers
async def handle_message_send(
    request_id: str, params: dict[str, Any], task_manager: BaseTaskManager
) -> MessageSendResponse:
    """Handle message/send RPC method."""
    try:
        # Convert to A2A message format
        message = Message(
            role="user",
            parts=[TextPart(text=params.get("message", {}).get("parts", [{}])[0].get("text", ""))],
        )

        # Create task parameters
        task_params = TaskSendParams(
            id=str(uuid4()),
            sessionId=params.get("contextId", str(uuid4())),
            message=message,
            metadata=params.get("metadata", {}),
        )

        # Send task
        send_request = SendTaskRequest(id=request_id, params=task_params)
        response = await task_manager.on_send_task(send_request)

        return MessageSendResponse(id=request_id, result=response.result)

    except Exception as e:
        logger.error(f"Error in message/send: {e}", exc_info=True)
        return MessageSendResponse(id=request_id, error=InternalError(message=str(e)))


async def handle_message_stream(
    request_id: str, params: dict[str, Any], task_manager: BaseTaskManager
) -> MessageStreamResponse:
    """Handle message/stream RPC method."""
    # For now, return a simple stream response
    # In production, this would set up SSE streaming
    try:
        message_response = await handle_message_send(request_id, params, task_manager)
        return MessageStreamResponse(
            id=request_id, result=message_response.result, error=message_response.error
        )
    except Exception as e:
        logger.error(f"Error in message/stream: {e}", exc_info=True)
        return MessageStreamResponse(id=request_id, error=InternalError(message=str(e)))


async def handle_task_get(
    request_id: str, params: dict[str, Any], task_manager: BaseTaskManager
) -> GetTaskResponse:
    """Handle tasks/get RPC method."""
    try:
        get_request = GetTaskRequest(id=request_id, params=TaskQueryParams(id=params.get("id", "")))
        return await task_manager.on_get_task(get_request)
    except Exception as e:
        logger.error(f"Error in tasks/get: {e}", exc_info=True)
        return GetTaskResponse(id=request_id, error=InternalError(message=str(e)))


async def handle_task_cancel(
    request_id: str, params: dict[str, Any], task_manager: BaseTaskManager
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
    request_id: str, params: dict[str, Any]
) -> AuthenticatedExtendedCardResponse:
    """Handle agent/authenticatedExtendedCard RPC method."""
    # Use demo agent card for now - in production would look up real agent
    demo_card = AgentCard(
        name="Demo Agent",
        description="A demonstration agent for testing A2A protocol",
        url="http://localhost:8000/v1/protocol",
        version="1.0.0",
        capabilities=AgentCapabilities(
            streaming=True, pushNotifications=False, stateTransitionHistory=True
        ),
        provider=AgentProvider(organization="AgentArea Demo"),
        skills=[
            AgentSkill(
                id="text-processing",
                name="Text Processing",
                description="Process and respond to text messages",
                inputModes=["text"],
                outputModes=["text"],
            )
        ],
    )

    return AuthenticatedExtendedCardResponse(id=request_id, result=demo_card)


# Agent discovery endpoint
@router.get("/agents/{agent_id}/card")
async def get_agent_card(
    agent_id: str, agent_service: AgentService = Depends(get_agent_service)
) -> AgentCard:
    """Get agent card for discovery using real agent service."""
    agent_card = await get_agent_card_by_id(agent_id, agent_service)
    if not agent_card:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
    return agent_card


# Health check endpoint
@router.get("/health")
async def health_check():
    """Health check for the protocol endpoint."""
    return {"status": "healthy", "protocol": "A2A", "version": "1.0.0"}
