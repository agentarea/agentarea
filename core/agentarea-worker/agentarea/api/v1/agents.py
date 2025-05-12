from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from agentarea.api.deps.services import get_agent_service
from core.agentarea.modules.agents.application.agent_service import AgentService
from agentarea.modules.agents.domain.models import Agent

router = APIRouter(prefix="/agents", tags=["agents"])

class AgentCreate(BaseModel):
    name: str
    capabilities: List[str]

class AgentUpdate(BaseModel):
    name: str | None = None
    capabilities: List[str] | None = None

class AgentResponse(BaseModel):
    id: UUID
    name: str
    capabilities: List[str]
    status: str
    
    @classmethod
    def from_domain(cls, agent: Agent) -> "AgentResponse":
        return cls(
            id=agent.id,
            name=agent.name,
            capabilities=agent.capabilities,
            status=agent.status
        )

@router.post("/", response_model=AgentResponse)
async def create_agent(
    data: AgentCreate,
    agent_service: AgentService = Depends(get_agent_service)
):
    agent = await agent_service.create_agent(
        name=data.name,
        capabilities=data.capabilities
    )
    return AgentResponse.from_domain(agent)

@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(
    agent_id: UUID,
    agent_service: AgentService = Depends(get_agent_service)
):
    agent = await agent_service.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return AgentResponse.from_domain(agent)

@router.get("/", response_model=List[AgentResponse])
async def list_agents(
    agent_service: AgentService = Depends(get_agent_service)
):
    agents = await agent_service.list()
    return [AgentResponse.from_domain(agent) for agent in agents]

@router.patch("/{agent_id}", response_model=AgentResponse)
async def update_agent(
    agent_id: UUID,
    data: AgentUpdate,
    agent_service: AgentService = Depends(get_agent_service)
):
    agent = await agent_service.update_agent(
        id=agent_id,
        name=data.name,
        capabilities=data.capabilities
    )
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return AgentResponse.from_domain(agent)

@router.delete("/{agent_id}")
async def delete_agent(
    agent_id: UUID,
    agent_service: AgentService = Depends(get_agent_service)
):
    success = await agent_service.delete_agent(agent_id)
    if not success:
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"status": "success"} 