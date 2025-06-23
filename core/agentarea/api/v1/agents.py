from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from agentarea.api.deps.services import get_agent_service
from agentarea.modules.agents.application.agent_service import AgentService
from agentarea.modules.agents.domain.models import Agent

router = APIRouter(prefix="/agents", tags=["agents"])


class MCPConfig(BaseModel):
    mcp_server_id: str
    requires_user_confirmation: bool | None = None
    config: dict | None = None


class ToolsConfig(BaseModel):
    mcp_server_configs: list[MCPConfig] | None = None
    planning: bool | None = None


class EventsConfig(BaseModel):
    events: list[str] | None = None


class AgentCreate(BaseModel):
    name: str
    description: str
    instruction: str
    model_id: str
    tools_config: ToolsConfig | None = None
    events_config: EventsConfig | None = None
    planning: bool | None = None


class AgentUpdate(BaseModel):
    name: str | None = None
    capabilities: list[str] | None = None
    description: str | None = None
    instruction: str | None = None
    model_id: str | None = None
    tools_config: ToolsConfig | None = None
    events_config: EventsConfig | None = None
    planning: bool | None = None


class AgentResponse(BaseModel):
    id: UUID
    name: str
    status: str
    description: str | None = None
    instruction: str | None = None
    model_id: str | None = None
    tools_config: dict | None = None
    events_config: dict | None = None
    planning: bool | None = None

    @classmethod
    def from_domain(cls, agent: Agent) -> "AgentResponse":
        return cls(
            id=agent.id,
            name=agent.name,
            status=agent.status,
            description=agent.description,
            instruction=agent.instruction,
            model_id=agent.model_id,
            tools_config=agent.tools_config,
            events_config=agent.events_config,
            planning=agent.planning,
        )


@router.post("/", response_model=AgentResponse)
async def create_agent(data: AgentCreate, agent_service: AgentService = Depends(get_agent_service)):
    """Create a new agent."""
    agent = await agent_service.create_agent(
        name=data.name,
        description=data.description,
        instruction=data.instruction,
        model_id=data.model_id,
        tools_config=data.tools_config.dict() if data.tools_config else None,
        events_config=data.events_config.dict() if data.events_config else None,
        planning=data.planning,
    )
    return AgentResponse.from_domain(agent)


@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(agent_id: UUID, agent_service: AgentService = Depends(get_agent_service)):
    """Get an agent by ID."""
    agent = await agent_service.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return AgentResponse.from_domain(agent)


@router.get("/", response_model=list[AgentResponse])
async def list_agents(agent_service: AgentService = Depends(get_agent_service)):
    """List all agents."""
    agents = await agent_service.list()
    return [AgentResponse.from_domain(agent) for agent in agents]


@router.patch("/{agent_id}", response_model=AgentResponse)
async def update_agent(
    agent_id: UUID,
    data: AgentUpdate,
    agent_service: AgentService = Depends(get_agent_service),
):
    """Update an agent."""
    agent = await agent_service.update_agent(
        id=agent_id,
        name=data.name,
        description=data.description,
        model_id=data.model_id,
        tools_config=data.tools_config.dict() if data.tools_config else None,
        events_config=data.events_config.dict() if data.events_config else None,
        planning=data.planning,
    )
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return AgentResponse.from_domain(agent)


@router.delete("/{agent_id}")
async def delete_agent(agent_id: UUID, agent_service: AgentService = Depends(get_agent_service)):
    """Delete an agent."""
    success = await agent_service.delete_agent(agent_id)
    if not success:
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"status": "success"}
