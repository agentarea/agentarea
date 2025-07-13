"""Legacy Protocol API Endpoints.

This module now contains only the AG-UI endpoints for CopilotKit integration.
A2A protocol endpoints have been moved to agent-specific endpoints at /v1/agents/{agent_id}/rpc

For A2A protocol compliance, use:
- /v1/agents/{agent_id}/rpc for JSON-RPC communication
- /v1/agents/{agent_id}/card for agent discovery
- /v1/agents/{agent_id}/tasks/ for REST task operations
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
        return None


# A2A JSON-RPC endpoints have been moved to agent-specific endpoints
# Use /v1/agents/{agent_id}/rpc for A2A protocol communication


# A2A JSON-RPC method handlers have been moved to agent-specific endpoints
# Use /v1/agents/{agent_id}/rpc for A2A protocol communication

# A2A agent discovery has been moved to agent-specific endpoints
# Use /v1/agents/{agent_id}/card for agent discovery


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


# Health check and deprecation notice
@router.get("/health")
async def health_check():
    """Health check for the protocol endpoint."""
    return {
        "status": "healthy",
        "protocol": "AG-UI only",
        "version": "1.0.0",
        "notice": "A2A protocol endpoints have been moved to agent-specific URLs",
        "a2a_endpoints": {
            "rpc": "/v1/agents/{agent_id}/rpc",
            "card": "/v1/agents/{agent_id}/card",
            "tasks": "/v1/agents/{agent_id}/tasks/"
        }
    }

@router.get("/")
async def protocol_info():
    """Information about protocol endpoints."""
    return {
        "message": "A2A protocol endpoints have been moved to agent-specific URLs",
        "deprecated_endpoints": {
            "/protocol/rpc": "moved to /v1/agents/{agent_id}/rpc",
            "/protocol/agents/{agent_id}/card": "moved to /v1/agents/{agent_id}/card"
        },
        "active_endpoints": {
            "/protocol/ag-ui": "AG-UI endpoint for CopilotKit integration"
        },
        "migration_guide": "Update your A2A clients to use agent-specific endpoints"
    }
