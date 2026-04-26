"""Agents API endpoints for managing AI agents."""

import re
from typing import Any, Literal
from uuid import UUID

from agentarea_agents.application.agent_service import AgentService
from agentarea_agents.domain.models import Agent
from agentarea_agents.schemas.import_export import ToolConfigYAML
from agentarea_agents_sdk.tools.code_tools_loader import get_code_tools_metadata
from agentarea_api.api.deps.services import (
    get_agent_service,
    get_mcp_server_instance_service,
    get_read_agent_service,
)
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.dependencies import UserContextDep
from agentarea_common.auth.permission import require_permission
from agentarea_common.config import get_database
from agentarea_llm.application.model_instance_service import ModelInstanceService
from agentarea_llm.infrastructure.model_instance_repository import ModelInstanceRepository
from agentarea_mcp.application.service import MCPServerInstanceService
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

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
            # OpenRouter-style: provider/model or provider/model:variant
            r"^[a-zA-Z][a-zA-Z0-9\-_.]*/[a-zA-Z][a-zA-Z0-9\-_.:]*(:[a-zA-Z0-9\-_.]+)?$",
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


class EventConfig(BaseModel):
    event_type: str
    config: dict | None = None
    enabled: bool = True


class EventsConfig(BaseModel):
    events: list[EventConfig] | None = None


class AgentCreate(BaseModel):
    name: str
    description: str
    instruction: str
    model_id: str
    tools: list[ToolConfigYAML] | None = None
    events_config: EventsConfig | None = None
    planning: bool | None = None
    a2ui_enabled: bool | None = None
    skill_ids: list[UUID] | None = None
    agent_type: str = "stateless"


class AgentUpdate(BaseModel):
    name: str | None = None
    capabilities: list[str] | None = None
    description: str | None = None
    instruction: str | None = None
    model_id: str | None = None
    tools: list[ToolConfigYAML] | None = None
    events_config: EventsConfig | None = None
    planning: bool | None = None
    a2ui_enabled: bool | None = None
    skill_ids: list[UUID] | None = None


class AgentResponse(BaseModel):
    id: UUID
    name: str
    status: str
    description: str | None = None
    instruction: str | None = None
    model_id: str | None = None
    tools: list[ToolConfigYAML] | None = None
    events_config: dict | None = None
    planning: bool | None = None
    a2ui_enabled: bool | None = None
    agent_type: str = "stateless"
    skills: list[dict] | None = None

    @classmethod
    def from_domain(cls, agent: Agent, include_skills: bool = False) -> "AgentResponse":
        tools = None
        if agent.tools:
            if isinstance(agent.tools, list):
                tools = [ToolConfigYAML(**tool) for tool in agent.tools]
            elif isinstance(agent.tools, dict):
                tools = []

        skills = None
        if include_skills and hasattr(agent, "skills") and agent.skills:
            skills = [
                {"id": str(skill.id), "name": skill.name, "description": skill.description}
                for skill in agent.skills
            ]

        return cls(
            id=agent.id,
            name=agent.name,
            status=agent.status,
            description=agent.description,
            instruction=agent.instruction,
            model_id=agent.model_id,
            tools=tools,
            events_config=agent.events_config,
            planning=agent.planning,
            a2ui_enabled=agent.a2ui_enabled,
            agent_type=agent.agent_type,
            skills=skills,
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

    # Validate code tools if provided
    if data.tools:
        available_code_tools = get_code_tools_metadata()
        invalid_tools = [
            tool_config.name
            for tool_config in data.tools
            if tool_config.type == "code" and tool_config.name not in available_code_tools
        ]
        if invalid_tools:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Invalid code tools: {invalid_tools}. "
                    f"Available tools: {list(available_code_tools.keys())}"
                ),
            )

    agent = await agent_service.create_agent(
        name=data.name,
        description=data.description,
        instruction=data.instruction,
        model_id=data.model_id,
        tools=[tool.model_dump(exclude_none=True) for tool in data.tools] if data.tools else None,
        events_config=data.events_config.model_dump() if data.events_config else None,
        planning=data.planning,
        a2ui_enabled=data.a2ui_enabled,
        skill_ids=data.skill_ids,
        agent_type=data.agent_type,
    )
    return AgentResponse.from_domain(agent)


class ToolResponse(BaseModel):
    """Unified tool response format."""

    name: str
    type: Literal["code", "mcp"]
    description: str
    input_schema: dict[str, Any]
    mcp_instance_id: UUID | None = None
    mcp_instance_name: str | None = None


@router.get("/tools", response_model=list[ToolResponse])
async def get_all_tools(
    user_context: UserContextDep,
    include: str = Query(
        "code,mcp", description="Comma-separated list of tool types to include (code, mcp)"
    ),
    mcp_instance_id: UUID | None = Query(
        None, description="Filter MCP tools by specific instance ID"
    ),
    mcp_service: MCPServerInstanceService = Depends(get_mcp_server_instance_service),
):
    """Get all available tools across all types.

    Returns a unified list of tools from:
    - Code tools (static, YAML-based)
    - MCP tools (dynamic, from running instances)

    Query Parameters:
        include: Comma-separated tool types (default: "code,mcp")
        mcp_instance_id: Filter MCP tools by instance (optional)

    Example:
        GET /v1/agents/tools?include=code,mcp
        GET /v1/agents/tools?include=code
        GET /v1/agents/tools?include=mcp&mcp_instance_id={uuid}
    """
    tools = []
    include_types = {t.strip() for t in include.split(",")}

    # Add code tools if requested
    if "code" in include_types:
        code_tools = get_code_tools_metadata()
        for tool_name, tool_meta in code_tools.items():
            tools.append(
                ToolResponse(
                    name=tool_name,
                    type="code",
                    description=tool_meta.get("description", ""),
                    input_schema=tool_meta.get("input_schema", {}),
                )
            )

    # Add MCP tools if requested
    if "mcp" in include_types:
        if mcp_instance_id:
            instance = await mcp_service.get(mcp_instance_id)
            if instance:
                mcp_tools = instance.get_available_tools()
                for tool in mcp_tools:
                    tools.append(
                        ToolResponse(
                            name=tool["function"]["name"],
                            type="mcp",
                            description=tool["function"].get("description", ""),
                            input_schema=tool["function"].get("parameters", {}),
                            mcp_instance_id=instance.id,
                            mcp_instance_name=instance.name,
                        )
                    )
        else:
            instances = await mcp_service.list()
            for instance in instances:
                mcp_tools = instance.get_available_tools()
                for tool in mcp_tools:
                    tools.append(
                        ToolResponse(
                            name=tool["function"]["name"],
                            type="mcp",
                            description=tool["function"].get("description", ""),
                            input_schema=tool["function"].get("parameters", {}),
                            mcp_instance_id=instance.id,
                            mcp_instance_name=instance.name,
                        )
                    )

    return tools


@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(
    agent_id: UUID,
    user_context: UserContextDep,
    agent_service: AgentService = Depends(get_read_agent_service),
):
    """Get an agent by ID."""
    agent = await agent_service.get_with_skills(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return AgentResponse.from_domain(agent, include_skills=True)


@router.get("", response_model=list[AgentResponse])
@router.get("/", response_model=list[AgentResponse])
async def list_agents(
    user_context: UserContextDep,
    agent_service: AgentService = Depends(get_read_agent_service),
):
    """List all workspace agents.

    Access Control:
        Returns all agents within the current user's workspace (workspace isolation).
        All users in the same workspace can see all workspace agents.

        Note: User-level access control should be implemented via authorization
        layer (future ReBAC) rather than query parameters.
    """
    agents = await agent_service.list()
    return [AgentResponse.from_domain(agent) for agent in agents]


@router.patch("/{agent_id}", response_model=AgentResponse)
async def update_agent(
    agent_id: UUID,
    data: AgentUpdate,
    user_context: UserContextDep,
    agent_service: AgentService = Depends(get_agent_service),
):
    """Update an agent."""
    await require_permission("edit", "agent", str(agent_id), user_context.user_id)
    # Validate model_id if it's being updated
    if data.model_id is not None:
        await validate_model_id(data.model_id, user_context)

    agent = await agent_service.update_agent(
        id=agent_id,
        name=data.name,
        description=data.description,
        model_id=data.model_id,
        tools=[tool.model_dump(exclude_none=True) for tool in data.tools] if data.tools else None,
        events_config=data.events_config.model_dump() if data.events_config else None,
        planning=data.planning,
        a2ui_enabled=data.a2ui_enabled,
        skill_ids=data.skill_ids,
    )
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    agent = await agent_service.get_with_skills(agent_id)
    return AgentResponse.from_domain(agent, include_skills=True)


@router.delete("/{agent_id}")
async def delete_agent(
    agent_id: UUID,
    user_context: UserContextDep,
    agent_service: AgentService = Depends(get_agent_service),
):
    """Delete an agent."""
    await require_permission("delete", "agent", str(agent_id), user_context.user_id)
    success = await agent_service.delete_agent(agent_id)
    if not success:
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"status": "success"}


# Include A2A protocol subroutes
router.include_router(agents_a2a.router, prefix="/{agent_id}", tags=["agents-a2a"])

# Include agent-specific well-known subroutes
router.include_router(agents_well_known.router, prefix="/{agent_id}", tags=["agents-well-known"])
