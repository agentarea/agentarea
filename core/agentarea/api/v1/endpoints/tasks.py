"""
Task management API endpoints for the AgentArea platform.

This module provides REST API endpoints for task operations including:
- Creating new tasks
- Retrieving tasks by various criteria
- Assigning tasks to agents
- Managing task statuses
"""

import logging
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Path, Body
from pydantic import BaseModel, Field

from agentarea.api.deps.services import get_task_service
from agentarea.api.deps.auth import get_current_user_id
from agentarea.modules.tasks.domain.models import Task, TaskType, TaskPriority, TaskComplexity
from agentarea.modules.tasks.task_service import TaskService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tasks", tags=["tasks"])


# Request/Response Models
class TaskCreateRequest(BaseModel):
    """Request model for creating a new task."""
    title: str = Field(..., description="Task title")
    description: str = Field(..., description="Detailed task description")
    task_type: TaskType = Field(default=TaskType.ANALYSIS, description="Type of task")
    priority: TaskPriority = Field(default=TaskPriority.MEDIUM, description="Task priority")
    agent_id: Optional[UUID] = Field(None, description="ID of agent to assign (optional)")
    parameters: dict = Field(default_factory=dict, description="Additional task parameters")


class TaskAssignRequest(BaseModel):
    """Request model for assigning a task to an agent."""
    agent_id: UUID = Field(..., description="ID of the agent to assign")


class TaskResponse(BaseModel):
    """Response model for task data."""
    id: str
    title: str
    description: str
    task_type: TaskType
    priority: TaskPriority
    status: dict
    assigned_agent_id: Optional[UUID] = None
    created_by: Optional[str] = None
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class TaskListResponse(BaseModel):
    """Response model for a list of tasks."""
    tasks: List[TaskResponse]
    total: int
    limit: int
    offset: int


# API Endpoints
@router.post("/", response_model=TaskResponse, status_code=201)
async def create_task(
    task_data: TaskCreateRequest,
    task_service: TaskService = Depends(get_task_service),
    user_id: str = Depends(get_current_user_id)
):
    """
    Create a new task.
    
    If an agent_id is provided, the task will be assigned to that agent immediately.
    """
    try:
        if task_data.agent_id:
            task = await task_service.create_and_start_simple_task(
                title=task_data.title,
                description=task_data.description,
                agent_id=task_data.agent_id,
                task_type=task_data.task_type,
                priority=task_data.priority,
                parameters=task_data.parameters
            )
        else:
            # Create task without assigning to an agent
            # This requires implementing a new method in TaskService
            # For now, we'll use the existing method but will need to update it
            task = await task_service.create_simple_task(
                title=task_data.title,
                description=task_data.description,
                task_type=task_data.task_type,
                priority=task_data.priority,
                parameters=task_data.parameters,
                created_by=user_id
            )
        
        return task
    except Exception as e:
        logger.error(f"Error creating task: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create task: {str(e)}")


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: str = Path(..., description="The ID of the task to retrieve"),
    task_service: TaskService = Depends(get_task_service)
):
    """
    Get a task by its ID.
    """
    task = await task_service.task_repository.get_by_id(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task with ID {task_id} not found")
    return task


@router.get("/user/{user_id}", response_model=TaskListResponse)
async def get_tasks_by_user(
    user_id: str = Path(..., description="The ID of the user"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of tasks to return"),
    offset: int = Query(0, ge=0, description="Number of tasks to skip"),
    task_service: TaskService = Depends(get_task_service)
):
    """
    Get tasks created by a specific user.
    """
    tasks = await task_service.get_tasks_by_user(user_id, limit, offset)
    # Get total count (would be more efficient with a dedicated count query)
    total = len(await task_service.get_tasks_by_user(user_id, 10000, 0))
    
    return TaskListResponse(
        tasks=tasks,
        total=total,
        limit=limit,
        offset=offset
    )


@router.get("/agent/{agent_id}", response_model=TaskListResponse)
async def get_tasks_by_agent(
    agent_id: UUID = Path(..., description="The ID of the agent"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of tasks to return"),
    offset: int = Query(0, ge=0, description="Number of tasks to skip"),
    task_service: TaskService = Depends(get_task_service)
):
    """
    Get tasks assigned to a specific agent.
    """
    tasks = await task_service.get_tasks_by_agent(agent_id, limit, offset)
    # Get total count (would be more efficient with a dedicated count query)
    total = len(await task_service.get_tasks_by_agent(agent_id, 10000, 0))
    
    return TaskListResponse(
        tasks=tasks,
        total=total,
        limit=limit,
        offset=offset
    )


@router.post("/{task_id}/assign", response_model=TaskResponse)
async def assign_task(
    task_id: str = Path(..., description="The ID of the task to assign"),
    assignment: TaskAssignRequest = Body(...),
    task_service: TaskService = Depends(get_task_service),
    user_id: str = Depends(get_current_user_id)
):
    """
    Assign a task to an agent.
    """
    try:
        task = await task_service.assign_task_to_agent(
            task_id=task_id,
            agent_id=assignment.agent_id,
            assigned_by=user_id
        )
        return task
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error assigning task: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to assign task: {str(e)}")


@router.get("/pending", response_model=TaskListResponse)
async def get_pending_tasks(
    limit: int = Query(20, ge=1, le=100, description="Maximum number of tasks to return"),
    task_service: TaskService = Depends(get_task_service)
):
    """
    Get pending tasks that need to be assigned to agents.
    """
    tasks = await task_service.get_pending_tasks(limit)
    
    return TaskListResponse(
        tasks=tasks,
        total=len(tasks),  # Since we're already limiting the results
        limit=limit,
        offset=0
    )


@router.post("/{task_id}/start", response_model=TaskResponse)
async def start_task(
    task_id: str = Path(..., description="The ID of the task to start"),
    task_service: TaskService = Depends(get_task_service)
):
    """
    Start execution of a task that has been assigned to an agent.
    """
    try:
        task = await task_service.task_repository.get_by_id(task_id)
        if not task:
            raise HTTPException(status_code=404, detail=f"Task with ID {task_id} not found")
        
        if not task.assigned_agent_id:
            raise HTTPException(status_code=400, detail="Task must be assigned to an agent before starting")
        
        # Create and publish task created event
        await task_service.start_task_execution(task)
        return task
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error starting task: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to start task: {str(e)}")
