from typing import List, Optional, Dict, Any
from uuid import UUID, uuid4
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from agentarea.api.deps.services import get_agent_service
from agentarea.api.deps.events import EventBrokerDep
from agentarea.modules.agents.application.agent_service import AgentService
from agentarea.modules.tasks.domain.events import TaskCreated


router = APIRouter(prefix="/agents/{agent_id}/tasks", tags=["agent-tasks"])


class TaskCreate(BaseModel):
    description: str
    parameters: Dict[str, Any] = {}


class TaskResponse(BaseModel):
    id: UUID
    agent_id: UUID
    description: str
    parameters: Dict[str, Any]
    status: str
    result: Optional[Dict[str, Any]] = None
    created_at: datetime
    
    @classmethod
    def create_new(cls, task_id: UUID, agent_id: UUID, description: str, parameters: Dict[str, Any]) -> "TaskResponse":
        """Create a new task response for a newly created task."""
        return cls(
            id=task_id,
            agent_id=agent_id,
            description=description,
            parameters=parameters,
            status="created",
            result=None,
            created_at=datetime.now(timezone.utc)
        )


@router.post("/", response_model=TaskResponse)
async def create_task_for_agent(
    agent_id: UUID,
    data: TaskCreate,
    event_broker: EventBrokerDep,
    agent_service: AgentService = Depends(get_agent_service),
):
    """Create a new task for the specified agent."""
    # Verify agent exists
    agent = await agent_service.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Generate a unique task ID
    task_id = uuid4()
    
    # Create the task response
    task_response = TaskResponse.create_new(
        task_id=task_id,
        agent_id=agent_id,
        description=data.description,
        parameters=data.parameters
    )
    
    # Create and publish TaskCreated event
    task_created_event = TaskCreated(
        task_id=str(task_id),
        agent_id=agent_id,
        description=data.description,
        parameters=data.parameters,
        metadata={
            "created_via": "api",
            "agent_name": agent.name,
            "created_at": task_response.created_at.isoformat()
        }
    )
    
    # Publish the event to the event broker
    await event_broker.publish(task_created_event)
    
    return task_response


@router.get("/", response_model=List[TaskResponse])
async def list_agent_tasks(
    agent_id: UUID,
    agent_service: AgentService = Depends(get_agent_service),
):
    """List all tasks for the specified agent."""
    # Verify agent exists
    agent = await agent_service.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    # TODO: Implement task listing when task service is available
    # For now, return empty list
    return []


@router.get("/{task_id}", response_model=TaskResponse)
async def get_agent_task(
    agent_id: UUID,
    task_id: UUID,
    agent_service: AgentService = Depends(get_agent_service),
):
    """Get a specific task for the specified agent."""
    # Verify agent exists
    agent = await agent_service.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    # TODO: Implement task retrieval when task service is available
    # For now, return 404
    raise HTTPException(status_code=404, detail="Task not found for this agent")
