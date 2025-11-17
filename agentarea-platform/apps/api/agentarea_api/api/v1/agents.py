"""Agents API endpoints for managing AI agents."""

import re
from uuid import UUID

from agentarea_agents.application.agent_service import AgentService
from agentarea_agents.domain.models import Agent
from agentarea_agents_sdk.tools.tool_manager import get_available_builtin_tools
from agentarea_api.api.deps.services import get_agent_service
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.dependencies import UserContextDep
from agentarea_common.config import get_database
from agentarea_llm.application.model_instance_service import ModelInstanceService
from agentarea_llm.infrastructure.model_instance_repository import ModelInstanceRepository
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

# Import A2A protocol subroutes
from . import agents_a2a, agents_well_known

router = APIRouter(prefix="/agents", tags=["agents"])


async def validate_model_id(model_id: str, user_context: UserContext) -> None:
    """Validate that model_id is an existing model instance or a valid identifier.

    Args:
        model_id: The model ID to validate
        user_context: Current user context

    Raises:
        HTTPException: If the model_id is invalid
    """
    # Create database session
    database = get_database()
    async with database.async_session_factory() as session:
        # Create model instance service
        model_instance_repository = ModelInstanceRepository(session, user_context)
        model_instance_service = ModelInstanceService(
            repository=model_instance_repository,
            event_broker=None,  # Not needed for validation
            secret_manager=None,  # Not needed for validation
        )

        # First, try to treat model_id as a UUID (model instance ID)
        try:
            model_uuid = UUID(model_id)
            model_instance = await model_instance_service.get(model_uuid)
            if model_instance:
                # Valid model instance ID
                return
        except ValueError:
            # Not a UUID, continue to check if it's a valid model name
            pass

        # If not a valid UUID or model instance not found, check if it's a
        # reasonable model identifier
        # For now, we'll allow certain patterns that are commonly used for model names
        valid_model_patterns = [
            # OpenAI-style models (specific patterns first)
            r"^gpt-[0-9.]+.*$",
            r"^claude-.*$",
            r"^llama.*$",
            r"^qwen.*$",
            r"^mistral.*$",
            # General model names - must contain at least one letter and one non-letter
            r"^[a-zA-Z][a-zA-Z0-9\-_.]*[a-zA-Z0-9]$",  # starts with letter
            r"^[a-zA-Z0-9]*[a-zA-Z][a-zA-Z0-9\-_.]*$",  # contains at least one letter
        ]

        for pattern in valid_model_patterns:
            if re.match(pattern, model_id, re.IGNORECASE):
                # Valid model name pattern - allow it
                return

        # If we get here, the model_id doesn't match any valid pattern
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid model_id '{model_id}'. Must be either a valid model "
                f"instance UUID or a recognized model identifier "
                f"(e.g., 'qwen2.5', 'gpt-4', 'claude-3', etc.)"
            ),
        )


class MCPToolConfig(BaseModel):
    tool_name: str
    requires_user_confirmation: bool = False


class MCPConfig(BaseModel):
    mcp_server_id: str
    allowed_tools: list[MCPToolConfig] | None = None


class BuiltinToolConfig(BaseModel):
    tool_name: str
    requires_user_confirmation: bool = False
    enabled: bool = True


class EventConfig(BaseModel):
    event_type: str
    config: dict | None = None
    enabled: bool = True


class ToolsConfig(BaseModel):
    mcp_server_configs: list[MCPConfig] | None = None
    builtin_tools: list[BuiltinToolConfig] | None = None
    planning: bool | None = None


class EventsConfig(BaseModel):
    events: list[EventConfig] | None = None


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
async def create_agent(
    data: AgentCreate,
    user_context: UserContextDep,
    agent_service: AgentService = Depends(get_agent_service),
):
    """Create a new agent."""
    # Validate model_id before creating agent
    await validate_model_id(data.model_id, user_context)

    # Validate builtin tools if provided
    if data.tools_config and data.tools_config.builtin_tools:
        available_tools = get_available_builtin_tools()
        invalid_tools = [
            tool_config.tool_name
            for tool_config in data.tools_config.builtin_tools
            if tool_config.tool_name not in available_tools
        ]
        if invalid_tools:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Invalid builtin tools: {invalid_tools}. "
                    f"Available tools: {list(available_tools.keys())}"
                ),
            )

    agent = await agent_service.create_agent(
        name=data.name,
        description=data.description,
        instruction=data.instruction,
        model_id=data.model_id,
        tools_config=data.tools_config.model_dump() if data.tools_config else None,
        events_config=data.events_config.model_dump() if data.events_config else None,
        planning=data.planning,
    )
    return AgentResponse.from_domain(agent)


@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(
    agent_id: UUID,
    user_context: UserContextDep,
    agent_service: AgentService = Depends(get_agent_service),
):
    """Get an agent by ID."""
    agent = await agent_service.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return AgentResponse.from_domain(agent)


@router.get("", response_model=list[AgentResponse])
@router.get("/", response_model=list[AgentResponse])
async def list_agents(
    user_context: UserContextDep,
    created_by: str | None = Query(
        None, description="Filter by creator: 'me' for current user's agents only"
    ),
    agent_service: AgentService = Depends(get_agent_service),
):
    """List all workspace agents with optional filtering by creator."""
    # Determine if we should filter by creator
    creator_scoped = created_by == "me"

    agents = await agent_service.list(creator_scoped=creator_scoped)
    return [AgentResponse.from_domain(agent) for agent in agents]


@router.patch("/{agent_id}", response_model=AgentResponse)
async def update_agent(
    agent_id: UUID,
    data: AgentUpdate,
    user_context: UserContextDep,
    agent_service: AgentService = Depends(get_agent_service),
):
    """Update an agent."""
    # Validate model_id if it's being updated
    if data.model_id is not None:
        await validate_model_id(data.model_id, user_context)

    agent = await agent_service.update_agent(
        id=agent_id,
        name=data.name,
        description=data.description,
        model_id=data.model_id,
        tools_config=data.tools_config.model_dump() if data.tools_config else None,
        events_config=data.events_config.model_dump() if data.events_config else None,
        planning=data.planning,
    )
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return AgentResponse.from_domain(agent)


@router.delete("/{agent_id}")
async def delete_agent(
    agent_id: UUID,
    user_context: UserContextDep,
    agent_service: AgentService = Depends(get_agent_service),
):
    """Delete an agent."""
    success = await agent_service.delete_agent(agent_id)
    if not success:
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"status": "success"}


@router.get("/tools/builtin")
async def get_builtin_tools(user_context: UserContextDep):
    """Get available builtin tools with full metadata including available methods."""
    return get_available_builtin_tools()


# Include A2A protocol subroutes
router.include_router(agents_a2a.router, prefix="/{agent_id}", tags=["agents-a2a"])

# Include agent-specific well-known subroutes
router.include_router(agents_well_known.router, prefix="/{agent_id}", tags=["agents-well-known"])
