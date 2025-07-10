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
from datetime import datetime
from pytz import UTC

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
    execution_id: str | None = Field(None, description="Temporal execution ID")


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
    agent_service: AgentService = Depends(get_agent_service),
):
    """Send a chat message to a real agent.

    Returns task_id immediately, executes via Temporal workflow asynchronously.
    """
    try:
        # Validate agent exists
        try:
            agent_uuid = UUID(request.agent_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid agent ID format")
        
        agent = await agent_service.get(agent_uuid)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")

        # Generate task and session IDs
        task_id = uuid4()
        session_id = request.session_id or f"chat-{uuid4()}"

        # Start Temporal workflow asynchronously - returns immediately!
        from agentarea_agents.application.temporal_workflow_service import TemporalWorkflowService
        workflow_service = TemporalWorkflowService()
        
        workflow_result = await workflow_service.execute_agent_task_async(
            agent_id=agent_uuid,
            task_query=request.content,
            user_id=request.user_id or "anonymous",
            session_id=session_id,
            task_parameters={
                "context": request.context or {},
                "task_type": "chat"
            },
            timeout_seconds=300,
        )
        
        execution_id = workflow_result.get("execution_id", f"task-{task_id}")

        # Return immediately with task_id - execution happens in background
        return ChatResponse(
            task_id=str(task_id),
            content="Message received. Processing...", # Will be updated when complete
            role="assistant", 
            session_id=session_id,
            agent_id=request.agent_id,
            status="processing", # Frontend will poll for completion
            timestamp=datetime.now(UTC).isoformat(),
            execution_id=execution_id, # For tracking workflow
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to send chat message: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/messages/{task_id}/status")
async def get_message_status(
    task_id: str,
    agent_service: AgentService = Depends(get_agent_service),
):
    """Get the status of a chat message task.
    
    Used for long polling - frontend calls this to check if message is complete.
    """
    try:
        from agentarea_agents.application.temporal_workflow_service import TemporalWorkflowService
        workflow_service = TemporalWorkflowService()
        
        # Get workflow status using execution_id pattern
        execution_id = f"agent-task-{task_id}"
        status = await workflow_service.get_workflow_status(execution_id)
        
        # Extract the actual response content if completed
        response_content = "Processing..."
        if status.get("status") == "completed":
            result = status.get("result", {})
            if isinstance(result, dict):
                response_content = result.get("response", result.get("content", "Task completed"))
            else:
                response_content = str(result)
        elif status.get("status") == "failed":
            error_msg = status.get("error", "Task failed")
            response_content = f"I apologize, but I encountered an error: {error_msg}"

        return {
            "task_id": task_id,
            "status": status.get("status", "unknown"),
            "content": response_content,
            "execution_id": execution_id,
            "start_time": status.get("start_time"),
            "end_time": status.get("end_time"),
            "error": status.get("error"),
            "timestamp": status.get("end_time") or datetime.now(UTC).isoformat(),
        }

    except Exception as e:
        logger.error(f"Failed to get message status: {e}", exc_info=True)
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
    agent_service: AgentService = Depends(get_agent_service),
):
    """Get list of real agents from database."""
    try:
        agents = await agent_service.list()
        
        return [
            AgentResponse(
                id=str(agent.id),
                name=agent.name,
                description=agent.description,
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
