"""Agent Protocol API Endpoints.

This module provides A2A protocol-compliant JSON-RPC endpoints for agent communication.
Also includes AG-UI endpoints for frontend integration with CopilotKit.
Focused on A2A protocol compliance - use /v1/agents/{agent_id}/tasks/ for REST task operations.
"""

import asyncio
import json
import logging
from typing import Any, AsyncGenerator
from uuid import UUID, uuid4

from agentarea_agents.application.agent_service import AgentService
from agentarea_api.api.deps.services import get_agent_service
from agentarea_common.utils.types import (
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
from agentarea_tasks.in_memory_task_manager import InMemoryTaskManager
from agentarea_tasks.task_manager import BaseTaskManager
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/protocol", tags=["protocol"])


# AG-UI Event Types
class AGUIEvent(BaseModel):
    """Base AG-UI event structure."""
    type: str
    timestamp: str | None = None


class LifecycleEvent(AGUIEvent):
    """AG-UI lifecycle event."""
    type: str = "lifecycle"
    status: str  # started, completed, failed


class TextDeltaEvent(AGUIEvent):
    """AG-UI text streaming event."""
    type: str = "text-delta"
    value: str


class ToolCallEvent(AGUIEvent):
    """AG-UI tool call event."""
    type: str = "tool-call"
    tool: str
    input: dict[str, Any]


class StateUpdateEvent(AGUIEvent):
    """AG-UI state update event."""
    type: str = "state-update"
    snapshot: dict[str, Any] | None = None
    diff: dict[str, Any] | None = None


class AGUIRequest(BaseModel):
    """AG-UI request format."""
    thread_id: str
    run_id: str | None = None
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]] = []
    context: list[dict[str, Any]] = []
    forwarded_props: dict[str, Any] = {}
    state: dict[str, Any] = {}


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


# AG-UI Endpoint for CopilotKit Integration
@router.post("/ag-ui")
async def handle_ag_ui_request(
    request: AGUIRequest, 
    task_manager: BaseTaskManager = Depends(get_task_manager)
) -> StreamingResponse:
    """AG-UI endpoint for CopilotKit integration.
    
    Converts A2A protocol events to AG-UI events for frontend consumption.
    """
    
    async def convert_a2a_to_agui_stream() -> AsyncGenerator[str, None]:
        """Convert A2A task events to AG-UI events."""
        try:
            # Send lifecycle start event
            yield f"data: {json.dumps(LifecycleEvent(status='started').model_dump())}\n\n"
            
            # Extract user message from AG-UI request
            if request.messages:
                last_message = request.messages[-1]
                user_text = last_message.get('content', '')
                
                # Create A2A message
                message = Message(
                    role="user",
                    parts=[TextPart(text=user_text)]
                )
                
                # Create A2A task parameters
                task_params = TaskSendParams(
                    id=str(uuid4()),
                    sessionId=request.thread_id,
                    message=message,
                    metadata={
                        "ag_ui_request": True,
                        "run_id": request.run_id,
                        "forwarded_props": request.forwarded_props
                    }
                )
                
                # Send task to A2A backend
                send_request = SendTaskRequest(id=str(uuid4()), params=task_params)
                a2a_response = await task_manager.on_send_task(send_request)
                
                if a2a_response.result and a2a_response.result.artifacts:
                    # Convert A2A artifacts to AG-UI text deltas
                    for artifact in a2a_response.result.artifacts:
                        if hasattr(artifact, 'parts'):
                            for part in artifact.parts:
                                if hasattr(part, 'text') and part.text:
                                    # Stream text as deltas
                                    words = part.text.split(' ')
                                    for word in words:
                                        event = TextDeltaEvent(value=word + ' ')
                                        yield f"data: {json.dumps(event.model_dump())}\n\n"
                                        await asyncio.sleep(0.01)  # Small delay for streaming effect
                
                # Send state update if needed
                if request.state:
                    state_event = StateUpdateEvent(
                        snapshot={
                            **request.state,
                            "last_task_id": task_params.id,
                            "session_id": request.thread_id
                        }
                    )
                    yield f"data: {json.dumps(state_event.model_dump())}\n\n"
            
            # Send lifecycle completion event
            yield f"data: {json.dumps(LifecycleEvent(status='completed').model_dump())}\n\n"
            
        except Exception as e:
            logger.error(f"Error in AG-UI stream: {e}", exc_info=True)
            error_event = LifecycleEvent(status='failed')
            yield f"data: {json.dumps(error_event.model_dump())}\n\n"
    
    return StreamingResponse(
        convert_a2a_to_agui_stream(),
        media_type="text/plain",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Content-Type": "text/event-stream"
        }
    )


# Health check endpoint
@router.get("/health")
async def health_check():
    """Health check for the protocol endpoint."""
    return {"status": "healthy", "protocol": "A2A + AG-UI", "version": "1.0.0"}
