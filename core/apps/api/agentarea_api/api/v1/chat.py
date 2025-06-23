"""Chat-Focused API Endpoints.

This module provides chat-specific functionality including:
- Conversational message sending (POST /chat/messages)
- Streaming responses (POST /chat/messages/stream)
- Conversation history (GET /chat/conversations/{session_id}/messages)
- WebSocket real-time chat (WS /chat/ws/{session_id})
- Agent discovery for chat UIs (GET /chat/agents)

For direct task management, use /v1/agents/{agent_id}/tasks/ endpoints.
For A2A JSON-RPC protocol, use /v1/protocol/rpc endpoint.
"""

import json
import logging
from typing import Any
from uuid import UUID, uuid4

from agentarea_agents.application.agent_service import AgentService
from agentarea_api.api.deps.services import get_agent_service
from agentarea_chat.unified_chat_service import UnifiedTaskService
from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])


# Unified Request/Response Models
class ChatMessageRequest(BaseModel):
    """Unified request model for sending chat messages."""

    content: str = Field(..., description="Message content")
    agent_id: str = Field(..., description="Target agent ID")
    user_id: str | None = Field(None, description="User sending the message")
    session_id: str | None = Field(None, description="Session/conversation ID")
    context: dict[str, Any] | None = Field(None, description="Additional context")


class ChatResponse(BaseModel):
    """Unified response model for chat messages."""

    task_id: str = Field(..., description="Task ID for the chat interaction")
    content: str = Field(..., description="Response content")
    role: str = Field(..., description="Role (user/assistant)")
    session_id: str = Field(..., description="Session/conversation ID")
    agent_id: str = Field(..., description="Agent ID")
    status: str = Field(..., description="Task status")
    timestamp: str = Field(..., description="Message timestamp")


class ConversationResponse(BaseModel):
    """Response model for conversation history."""

    session_id: str = Field(..., description="Session/conversation ID")
    messages: list[dict[str, Any]] = Field(..., description="List of messages")
    agent_id: str | None = Field(None, description="Primary agent ID")
    message_count: int = Field(..., description="Number of messages")


class AgentResponse(BaseModel):
    """Response model for agent information."""

    id: str = Field(..., description="Agent ID")
    name: str = Field(..., description="Agent name")
    description: str | None = Field(None, description="Agent description")
    status: str = Field(..., description="Agent status")


# Dependencies
async def get_unified_chat_service() -> UnifiedTaskService:
    """Get unified chat service instance."""
    return UnifiedTaskService()


# Core Chat Endpoints
@router.post("/messages", response_model=ChatResponse)
async def send_message(
    request: ChatMessageRequest,
    chat_service: UnifiedTaskService = Depends(get_unified_chat_service),
):
    """Send a chat message to an agent.

    Unified endpoint that handles both A2A protocol and REST API.
    """
    try:
        # Generate session ID if not provided
        session_id = request.session_id or f"chat-{uuid4()}"

        # Send message using the unified service
        response = await chat_service.send_task(
            content=request.content,
            agent_id=request.agent_id,
            task_type="chat",
            session_id=session_id,
            context=request.context,
            user_id=request.user_id,
        )

        return ChatResponse(
            task_id=response.get("id", str(uuid4())),
            content=response.get("content", f"Response to: {request.content}"),
            role="assistant",
            session_id=session_id,
            agent_id=request.agent_id,
            status=response.get("status", "completed"),
            timestamp=response.get("timestamp", ""),
        )

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        logger.error(f"Failed to send chat message: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/messages/stream")
async def stream_message(
    request: ChatMessageRequest,
    chat_service: UnifiedTaskService = Depends(get_unified_chat_service),
):
    """Stream a chat message response from an agent.

    Returns Server-Sent Events (SSE) compatible with A2A protocol.
    """
    try:
        # Generate session ID if not provided
        session_id = request.session_id or f"chat-{uuid4()}"

        async def generate_stream():
            try:
                async for chunk in chat_service.stream_task(
                    content=request.content,
                    agent_id=request.agent_id,
                    task_type="chat_stream",
                    session_id=session_id,
                    context=request.context,
                    user_id=request.user_id,
                ):
                    yield f"data: {json.dumps(chunk)}\n\n"

            except Exception as e:
                error_chunk = {"error": str(e), "status": "error"}
                yield f"data: {json.dumps(error_chunk)}\n\n"

        return StreamingResponse(
            generate_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "*",
            },
        )

    except Exception as e:
        logger.error(f"Failed to stream chat message: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e


# Conversation Management
@router.get("/conversations/{session_id}/messages", response_model=ConversationResponse)
async def get_conversation_history(
    session_id: str, chat_service: UnifiedTaskService = Depends(get_unified_chat_service)
):
    """Get conversation history for a session."""
    try:
        messages = await chat_service.get_session_history(session_id)

        # Extract agent_id from messages if available
        agent_id = None
        for msg in messages:
            if msg.get("agent_id"):
                agent_id = msg["agent_id"]
                break

        return ConversationResponse(
            session_id=session_id, messages=messages, agent_id=agent_id, message_count=len(messages)
        )

    except Exception as e:
        logger.error(f"Failed to get conversation history: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/conversations")
async def list_conversations(
    user_id: str | None = Query(None, description="Filter by user ID"),
    chat_service: UnifiedTaskService = Depends(get_unified_chat_service),
):
    """List all conversations for a user."""
    try:
        conversations = await chat_service.list_sessions(user_id)
        return {"conversations": conversations}

    except Exception as e:
        logger.error(f"Failed to list conversations: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e


# Agent Management
@router.get("/agents", response_model=list[AgentResponse])
async def get_available_agents(
    chat_service: UnifiedTaskService = Depends(get_unified_chat_service),
):
    """Get list of available agents."""
    try:
        agents = await chat_service.get_available_agents()

        return [
            AgentResponse(
                id=agent.get("id", ""),
                name=agent.get("name", "Unknown"),
                description=agent.get("description"),
                status="active",
            )
            for agent in agents
        ]

    except Exception as e:
        logger.error(f"Failed to get agents: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/agents/{agent_id}", response_model=AgentResponse)
async def get_agent(agent_id: str, agent_service: AgentService = Depends(get_agent_service)):
    """Get details for a specific agent."""
    try:
        # Convert to UUID and get agent
        agent_uuid = UUID(agent_id)
        agent = await agent_service.get(agent_uuid)

        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

        return AgentResponse(
            id=str(agent.id), name=agent.name, description=agent.description, status="active"
        )

    except ValueError:
        raise HTTPException(
            status_code=400, detail=f"Invalid agent ID format: {agent_id}"
        ) from None
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get agent {agent_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e


# NOTE: Task management endpoints have been moved to /v1/agents/{agent_id}/tasks/
# For task operations, use:
#   - GET /v1/agents/{agent_id}/tasks/{task_id} - Get task
#   - DELETE /v1/agents/{agent_id}/tasks/{task_id} - Cancel task
# A2A JSON-RPC protocol compliance is handled by /v1/protocol/rpc


# WebSocket Support
@router.websocket("/ws/{session_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    session_id: str,
    chat_service: UnifiedTaskService = Depends(get_unified_chat_service),
):
    """WebSocket endpoint for real-time chat."""
    await websocket.accept()

    try:
        logger.info(f"WebSocket connection established for session {session_id}")

        while True:
            # Wait for messages from client
            data = await websocket.receive_text()
            message_data = json.loads(data)

            # Process message and send response
            if message_data.get("type") == "message":
                try:
                    # Send message through unified service
                    response = await chat_service.send_task(
                        content=message_data.get("content", ""),
                        agent_id=message_data.get("agent_id", "default"),
                        task_type="websocket",
                        session_id=session_id,
                        user_id=message_data.get("user_id"),
                    )

                    # Send response back
                    await websocket.send_text(
                        json.dumps(
                            {
                                "type": "message",
                                "task_id": response.get("id", ""),
                                "content": response.get("content", ""),
                                "role": "assistant",
                                "session_id": session_id,
                                "timestamp": response.get("timestamp", ""),
                            }
                        )
                    )

                except Exception as e:
                    await websocket.send_text(json.dumps({"type": "error", "message": str(e)}))

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for session {session_id}")
    except Exception as e:
        logger.error(f"WebSocket error for session {session_id}: {e}", exc_info=True)
        try:
            await websocket.close()
        except Exception:
            pass


# Health Check
@router.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "unified-chat-api",
        "version": "1.0.0",
        "features": [
            "unified-chat",
            "a2a-protocol",
            "rest-api",
            "streaming",
            "websockets",
            "conversation-history",
            "agent-management",
        ],
    }
