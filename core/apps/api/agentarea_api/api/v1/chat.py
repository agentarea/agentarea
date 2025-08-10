"""Chat-Focused API Endpoints.

This module provides chat-specific functionality including:
- Conversational message sending (POST /chat/messages)
- Message status polling (GET /chat/messages/{task_id}/status)
- Agent discovery for chat UIs (GET /chat/agents)

For direct task management, use /v1/agents/{agent_id}/tasks/ endpoints.
For A2A JSON-RPC protocol, use /v1/protocol/rpc endpoint.
"""

import json
import logging
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from agentarea_agents.application.agent_service import AgentService
from agentarea_agents.application.temporal_workflow_service import TemporalWorkflowService
from agentarea_api.api.deps.events import EventBrokerDep
from agentarea_api.api.deps.services import (
    get_agent_service,
    get_task_service,
    get_temporal_workflow_service,
)
from agentarea_tasks.domain.models import TaskCreate
from agentarea_tasks.task_service import TaskService
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from pytz import UTC

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


class AgentResponse(BaseModel):
    """Response model for agent information."""

    id: str = Field(..., description="Agent ID")
    name: str = Field(..., description="Agent name")
    description: str | None = Field(None, description="Agent description")
    status: str = Field(..., description="Agent status")


# Core Chat Endpoints
@router.post("/messages", response_model=ChatResponse)
async def send_message(
    request: ChatMessageRequest,
    event_broker: EventBrokerDep,
    agent_service: AgentService = Depends(get_agent_service),
    workflow_service: TemporalWorkflowService = Depends(get_temporal_workflow_service),
    task_service: TaskService = Depends(get_task_service),
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
        task_id_str = str(task_id)
        session_id = request.session_id or f"chat-{uuid4()}"

        logger.info(f"Generated new task ID: {task_id_str} for agent {agent_uuid}")

        # Create task record immediately - this ensures the task is visible in tasks API
        # Status starts as "pending" to indicate workflow hasn't started yet
        task_parameters = {
            "context": request.context or {},
            "task_type": "chat",
            "session_id": session_id,
        }

        task_create = TaskCreate(
            agent_id=agent_uuid,
            description=request.content,
            parameters=task_parameters,
            user_id=request.user_id or "anonymous",
            metadata={
                "created_via": "chat",
                "agent_name": agent.name,
                "session_id": session_id,
                "status": "created",
                "task_id": task_id_str,  # Store the task ID in metadata for now
            },
        )

        # Create task using the task service (which handles repository creation properly)
        try:
            task = await task_service.create_and_execute_task_with_workflow(
                agent_id=agent_uuid,
                description=request.content,
                parameters=task_parameters,
                user_id=request.user_id or "anonymous",
                enable_agent_communication=True,
            )
            logger.info(f"Chat task {task.id} created and submitted for agent {agent_uuid}")
        except Exception as e:
            logger.error(f"Failed to create chat task: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to create chat task: {e}")

        # The task service already handles workflow execution, so we can use the task directly
        execution_id = task.execution_id
        status = task.status

        # Update task_id_str to match the actual task ID created
        task_id_str = str(task.id)

        # Task service handles workflow execution and event publishing, so we're done
        logger.info(f"Chat task {task_id_str} created with status {status} for agent {agent_uuid}")

        # Return immediately with task_id - execution happens in background
        return ChatResponse(
            task_id=task_id_str,
            content="Message received. Processing...",  # Will be updated when complete
            role="assistant",
            session_id=session_id,
            agent_id=request.agent_id,
            status=status,  # Will be "processing" or "failed"
            timestamp=datetime.now(UTC).isoformat(),
            execution_id=execution_id,  # For tracking workflow
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to send chat message: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/messages/{task_id}/status")
async def get_message_status(
    task_id: str,
    workflow_service: TemporalWorkflowService = Depends(get_temporal_workflow_service),
):
    """Get the status of a chat message task.

    Used for long polling - frontend calls this to check if message is complete.
    """
    try:
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


# Simple WebSocket Support for basic real-time communication
@router.websocket("/ws/{session_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    session_id: str,
    agent_service: AgentService = Depends(get_agent_service),
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
                    agent_id = message_data.get("agent_id")
                    content = message_data.get("content", "")

                    if not agent_id or not content:
                        await websocket.send_text(
                            json.dumps({"type": "error", "message": "Missing agent_id or content"})
                        )
                        continue

                    # Validate agent exists
                    try:
                        agent_uuid = UUID(agent_id)
                        agent = await agent_service.get(agent_uuid)
                        if not agent:
                            raise HTTPException(status_code=404, detail="Agent not found")
                    except ValueError:
                        await websocket.send_text(
                            json.dumps({"type": "error", "message": "Invalid agent ID format"})
                        )
                        continue

                    # Send acknowledgment immediately
                    await websocket.send_text(
                        json.dumps(
                            {
                                "type": "message",
                                "content": "Message received. Processing...",
                                "role": "assistant",
                                "session_id": session_id,
                                "timestamp": datetime.now(UTC).isoformat(),
                                "status": "processing",
                            }
                        )
                    )

                    # Start background task via Temporal (WebSocket will close, but that's okay)
                    # For real-time responses, consider implementing WebSocket-specific streaming
                    logger.info(f"WebSocket message received for agent {agent_id}: {content}")

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
