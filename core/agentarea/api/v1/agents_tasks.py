from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from agentarea.api.deps.services import get_agent_service, get_task_service
from agentarea.modules.agents.application.service import AgentService
from agentarea.modules.tasks.application.service import TaskService
from agentarea.modules.tasks.domain.models import Task

router = APIRouter(prefix="/agents/{agent_id}/tasks", tags=["agent-tasks"])


class TaskCreate(BaseModel):
    description: str
    parameters: dict = {}


class TaskResponse(BaseModel):
    id: UUID
    agent_id: UUID
    description: str
    parameters: dict
    status: str
    result: Optional[dict] = None

    @classmethod
    def from_domain(cls, task: Task) -> "TaskResponse":
        return cls(
            id=task.id,
            agent_id=task.agent_id,
            description=task.description,
            parameters=task.parameters,
            status=task.status,
            result=task.result,
        )


@router.post("/", response_model=TaskResponse)
async def create_task_for_agent(
    agent_id: UUID,
    data: TaskCreate,
    agent_service: AgentService = Depends(get_agent_service),
    task_service: TaskService = Depends(get_task_service),
):
    # Verify agent exists
    agent = await agent_service.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    # Create task for the agent
    task = await task_service.create_task(
        agent_id=agent_id,
        description=data.description,
        parameters=data.parameters
    )
    
    return TaskResponse.from_domain(task)


@router.get("/", response_model=List[TaskResponse])
async def list_agent_tasks(
    agent_id: UUID,
    agent_service: AgentService = Depends(get_agent_service),
    task_service: TaskService = Depends(get_task_service),
):
    # Verify agent exists
    agent = await agent_service.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    # Get all tasks for the agent
    tasks = await task_service.list_by_agent(agent_id)
    return [TaskResponse.from_domain(task) for task in tasks]


@router.get("/{task_id}", response_model=TaskResponse)
async def get_agent_task(
    agent_id: UUID,
    task_id: UUID,
    agent_service: AgentService = Depends(get_agent_service),
    task_service: TaskService = Depends(get_task_service),
):
    # Verify agent exists
    agent = await agent_service.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    # Get the specific task
    task = await task_service.get(task_id)
    if not task or task.agent_id != agent_id:
        raise HTTPException(status_code=404, detail="Task not found for this agent")
    
    return TaskResponse.from_domain(task)
