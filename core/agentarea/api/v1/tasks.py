"""
Task API endpoints for creating and managing tasks.
"""

import logging
from typing import Optional, Dict, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from agentarea.api.deps.events import EventBrokerDep
from agentarea.api.deps.services import get_agent_service
from agentarea.modules.agents.application.agent_service import AgentService
from agentarea.modules.tasks.task_service import TaskService
from agentarea.modules.tasks.domain.models import TaskType, TaskPriority

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tasks", tags=["tasks"])


class CreateTestTaskRequest(BaseModel):
    agent_id: UUID


class CreateTaskRequest(BaseModel):
    title: str
    description: str
    agent_id: UUID
    task_type: TaskType = TaskType.ANALYSIS
    priority: TaskPriority = TaskPriority.MEDIUM
    parameters: Optional[Dict[str, Any]] = None


class CreateMCPTaskRequest(BaseModel):
    title: str
    description: str
    mcp_server_id: str
    tool_name: str
    agent_id: UUID
    tool_configuration: Optional[Dict[str, Any]] = None
    priority: TaskPriority = TaskPriority.MEDIUM


class TaskResponse(BaseModel):
    id: str
    title: str
    description: str
    task_type: str
    priority: str
    status: str
    agent_id: Optional[str] = None
    created_at: str
    metadata: Dict[str, Any]


@router.post("/test", response_model=TaskResponse)
async def create_test_task(
    request: CreateTestTaskRequest,
    event_broker: EventBrokerDep,
    agent_service: AgentService = Depends(get_agent_service),
):
    """Create and start a test task for the specified agent."""
    try:
        # Verify agent exists
        agent = await agent_service.get(request.agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")

        # Create task service
        task_service = TaskService(event_broker)
        
        # Create and start test task
        task = await task_service.create_and_start_test_task(request.agent_id)
        
        logger.info(f"Test task {task.id} created and started for agent {request.agent_id}")
        
        return TaskResponse(
            id=task.id,
            title=task.title,
            description=task.description,
            task_type=task.task_type.value,
            priority=task.priority.value,
            status=task.status.state.value,
            agent_id=str(task.assigned_agent_id) if task.assigned_agent_id else None,
            created_at=task.created_at.isoformat(),
            metadata=task.metadata
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create test task: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create test task")


@router.post("/", response_model=TaskResponse)
async def create_task(
    request: CreateTaskRequest,
    event_broker: EventBrokerDep,
    agent_service: AgentService = Depends(get_agent_service),
):
    """Create and start a task for the specified agent."""
    try:
        # Verify agent exists
        agent = await agent_service.get(request.agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")

        # Create task service
        task_service = TaskService(event_broker)
        
        # Create and start task
        task = await task_service.create_and_start_simple_task(
            title=request.title,
            description=request.description,
            agent_id=request.agent_id,
            task_type=request.task_type,
            priority=request.priority,
            parameters=request.parameters
        )
        
        logger.info(f"Task {task.id} '{task.title}' created and started for agent {request.agent_id}")
        
        return TaskResponse(
            id=task.id,
            title=task.title,
            description=task.description,
            task_type=task.task_type.value,
            priority=task.priority.value,
            status=task.status.state.value,
            agent_id=str(task.assigned_agent_id) if task.assigned_agent_id else None,
            created_at=task.created_at.isoformat(),
            metadata=task.metadata
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create task: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create task")


@router.post("/mcp", response_model=TaskResponse)
async def create_mcp_task(
    request: CreateMCPTaskRequest,
    event_broker: EventBrokerDep,
    agent_service: AgentService = Depends(get_agent_service),
):
    """Create and start an MCP integration task for the specified agent."""
    try:
        # Verify agent exists
        agent = await agent_service.get(request.agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")

        # Create task service
        task_service = TaskService(event_broker)
        
        # Create and start MCP task
        task = await task_service.create_and_start_mcp_task(
            title=request.title,
            description=request.description,
            mcp_server_id=request.mcp_server_id,
            tool_name=request.tool_name,
            agent_id=request.agent_id,
            tool_configuration=request.tool_configuration,
            priority=request.priority
        )
        
        logger.info(f"MCP task {task.id} '{task.title}' created for server {request.mcp_server_id}")
        
        return TaskResponse(
            id=task.id,
            title=task.title,
            description=task.description,
            task_type=task.task_type.value,
            priority=task.priority.value,
            status=task.status.state.value,
            agent_id=str(task.assigned_agent_id) if task.assigned_agent_id else None,
            created_at=task.created_at.isoformat(),
            metadata=task.metadata
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create MCP task: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create MCP task") 