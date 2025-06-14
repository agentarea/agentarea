"""
Task API endpoints for the AgentArea platform.

This module provides both A2A-compliant JSON-RPC style endpoints and REST endpoints
for task management, including:
- Sending tasks to agents
- Retrieving tasks by user ID
- Retrieving tasks by agent ID
"""

import logging
from typing import List, Optional, Dict, Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Path
from pydantic import BaseModel, Field

from agentarea.common.di.container import get_instance
from agentarea.common.utils.types import (
    Task,
    TaskState,
    Message,
    TextPart,
    SendTaskRequest,
    SendTaskResponse,
    TaskSendParams,
    JSONRPCMessage,
)
from agentarea.modules.tasks.task_manager import BaseTaskManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tasks", tags=["tasks"])


# Request/Response Models for REST API
class TaskCreateRequest(BaseModel):
    """Request model for creating a new task."""
    message: str = Field(..., description="Task message content")
    user_id: Optional[str] = Field(None, description="ID of the user creating the task")
    agent_id: Optional[str] = Field(None, description="ID of the agent to assign the task to")
    session_id: Optional[str] = Field(None, description="Session ID for the task")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional task metadata")


class TaskResponse(BaseModel):
    """Response model for task data."""
    id: str
    session_id: Optional[str] = None
    status: Dict[str, Any]
    metadata: Optional[Dict[str, Any]] = None

    class Config:
        from_attributes = True


class TaskListResponse(BaseModel):
    """Response model for a list of tasks."""
    tasks: List[TaskResponse]
    count: int


# Dependency to get task manager
async def get_task_manager() -> BaseTaskManager:
    """Get the task manager instance."""
    return get_instance(BaseTaskManager)


# A2A Protocol JSON-RPC style endpoints
@router.post("/send", response_model=SendTaskResponse)
async def send_task(
    request: SendTaskRequest,
    task_manager: BaseTaskManager = Depends(get_task_manager)
) -> SendTaskResponse:
    """
    Send a task using A2A protocol format.
    
    This endpoint follows the A2A protocol's JSON-RPC style for task creation.
    """
    logger.info(f"Received task send request for task {request.params.id}")
    return await task_manager.on_send_task(request)


# REST API endpoints
@router.post("/", response_model=TaskResponse, status_code=201)
async def create_task(
    task_data: TaskCreateRequest,
    task_manager: BaseTaskManager = Depends(get_task_manager)
) -> TaskResponse:
    """
    Create a new task with user and agent metadata.
    
    This is a REST-style endpoint that creates a task and internally
    uses the A2A protocol format.
    """
    # Generate a unique task ID
    task_id = str(uuid4())
    
    # Create a message from the text
    message = Message(
        role="user",
        parts=[TextPart(text=task_data.message)]
    )
    
    # Prepare metadata with user and agent IDs if provided
    metadata = task_data.metadata or {}
    if task_data.user_id:
        metadata["user_id"] = task_data.user_id
    if task_data.agent_id:
        metadata["agent_id"] = task_data.agent_id
    
    # Create task send parameters
    params = TaskSendParams(
        id=task_id,
        sessionId=task_data.session_id or str(uuid4()),
        message=message,
        metadata=metadata
    )
    
    # Create and send the task using A2A protocol
    request = SendTaskRequest(
        id=str(uuid4()),
        params=params
    )
    
    try:
        response = await task_manager.on_send_task(request)
        if response.error:
            raise HTTPException(
                status_code=400,
                detail=f"Failed to create task: {response.error.message}"
            )
        return response.result
    except Exception as e:
        logger.error(f"Error creating task: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create task: {str(e)}")


@router.get("/user/{user_id}", response_model=TaskListResponse)
async def get_tasks_by_user(
    user_id: str = Path(..., description="The ID of the user"),
    task_manager: BaseTaskManager = Depends(get_task_manager)
) -> TaskListResponse:
    """
    Get all tasks associated with a specific user.
    
    Returns tasks where the user_id is stored in the task metadata.
    """
    try:
        tasks = await task_manager.on_get_tasks_by_user(user_id)
        return TaskListResponse(
            tasks=[TaskResponse(
                id=task.id,
                session_id=task.sessionId,
                status=task.status.model_dump(),
                metadata=task.metadata
            ) for task in tasks],
            count=len(tasks)
        )
    except Exception as e:
        logger.error(f"Error retrieving tasks for user {user_id}: {e}")
        raise HTTPException(
            status_code=500, 
            detail=f"Failed to retrieve tasks for user {user_id}: {str(e)}"
        )


@router.get("/agent/{agent_id}", response_model=TaskListResponse)
async def get_tasks_by_agent(
    agent_id: str = Path(..., description="The ID of the agent"),
    task_manager: BaseTaskManager = Depends(get_task_manager)
) -> TaskListResponse:
    """
    Get all tasks assigned to a specific agent.
    
    Returns tasks where the agent_id is stored in the task metadata.
    """
    try:
        tasks = await task_manager.on_get_tasks_by_agent(agent_id)
        return TaskListResponse(
            tasks=[TaskResponse(
                id=task.id,
                session_id=task.sessionId,
                status=task.status.model_dump(),
                metadata=task.metadata
            ) for task in tasks],
            count=len(tasks)
        )
    except Exception as e:
        logger.error(f"Error retrieving tasks for agent {agent_id}: {e}")
        raise HTTPException(
            status_code=500, 
            detail=f"Failed to retrieve tasks for agent {agent_id}: {str(e)}"
        )


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: str = Path(..., description="The ID of the task to retrieve"),
    task_manager: BaseTaskManager = Depends(get_task_manager)
) -> TaskResponse:
    """
    Get a task by its ID.
    
    This is a REST-style endpoint that internally uses the A2A protocol.
    """
    from agentarea.common.utils.types import GetTaskRequest, TaskQueryParams
    
    # Create and send the request using A2A protocol
    request = GetTaskRequest(
        id=str(uuid4()),
        params=TaskQueryParams(id=task_id)
    )
    
    try:
        response = await task_manager.on_get_task(request)
        if response.error:
            if response.error.code == -32001:  # Task not found error
                raise HTTPException(status_code=404, detail=f"Task with ID {task_id} not found")
            raise HTTPException(
                status_code=400,
                detail=f"Failed to retrieve task: {response.error.message}"
            )
        
        task = response.result
        return TaskResponse(
            id=task.id,
            session_id=task.sessionId,
            status=task.status.model_dump(),
            metadata=task.metadata
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving task {task_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to retrieve task: {str(e)}")
