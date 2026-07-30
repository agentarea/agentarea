"""Agents API endpoints for managing AI agents."""

import logging
from contextlib import suppress
from typing import Annotated, Any, Literal, cast
from uuid import UUID

from agentarea_agents.application.agent_service import AgentService
from agentarea_agents.domain.models import Agent
from agentarea_agents.schemas.dto import (
    AgentCreate,
    AgentUpdate,
)
from agentarea_agents.schemas.import_export import (
    TOOL_CONFIG_ADAPTER,
    ToolConfig,
)
from agentarea_agents_sdk.tools.code_tools_loader import get_code_tools_metadata
from agentarea_api.api.deps.services import (
    get_agent_service,
    get_mcp_server_instance_service,
    get_read_agent_service,
)
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.dependencies import UserContextDep
from agentarea_common.auth.permission import require_permission
from agentarea_common.config.database import get_db_session
from agentarea_mcp.application.service import MCPServerInstanceService
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from . import agents_a2a, agents_well_known
from ._access_control_grants import grant_resource_owner
from ._approval_policy_sync import (
    apply_approval_targets,
    approval_targets_for_agents,
)

DatabaseSessionDep = Annotated[AsyncSession, Depends(get_db_session)]

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agents", tags=["agents"])


class AgentResponse(BaseModel):
    id: UUID
    slug: str
    name: str
    status: str
    description: str | None = None
    instruction: str | None = None
    model_id: str | None = None
    tools: list[ToolConfig] | None = None
    events_config: dict | None = None
    planning: bool | None = None
    a2ui_enabled: bool | None = None
    agent_type: str = "stateless"
    skills: list[dict] | None = None
    # Catalog provenance (ADR-003). ``is_catalog`` marks a read-only built-in
    # agent that has not been forked into the workspace yet.
    is_catalog: bool = False
    registry_item_id: str | None = None
    update_available: bool = False

    @classmethod
    def from_domain(cls, agent: Agent, include_skills: bool = False) -> "AgentResponse":
        tools = None
        if agent.tools:
            agent_tools = cast(Any, agent.tools)
            if isinstance(agent_tools, list):
                tools = []
                for tool in agent_tools:
                    if not isinstance(tool, dict):
                        continue
                    try:
                        tools.append(TOOL_CONFIG_ADAPTER.validate_python(tool))
                    except ValidationError:
                        # Skip a malformed/legacy tool entry rather than failing
                        # the whole agent read.
                        logger.warning(
                            "Skipping unparseable tool config", extra={"tool_config": tool}
                        )
            elif isinstance(agent_tools, dict):
                tools = []

        skills = None
        if include_skills and hasattr(agent, "skills") and agent.skills:
            skills = [
                {"id": str(skill.id), "name": skill.name, "description": skill.description}
                for skill in agent.skills
            ]

        registry_item_id = getattr(agent, "registry_item_id", None)
        return cls(
            id=cast(UUID, agent.id),
            slug=str(agent.slug),
            name=str(agent.name),
            status=str(agent.status),
            description=cast(str | None, agent.description),
            instruction=cast(str | None, agent.instruction),
            model_id=cast(str | None, agent.model_id),
            tools=tools,
            events_config=cast(dict | None, agent.events_config),
            planning=cast(bool | None, agent.planning),
            a2ui_enabled=cast(bool | None, agent.a2ui_enabled),
            agent_type=str(agent.agent_type),
            skills=skills,
            is_catalog=bool(getattr(agent, "is_catalog", False)),
            registry_item_id=str(registry_item_id) if registry_item_id else None,
            update_available=bool(getattr(agent, "update_available", False)),
        )


async def _resolve_agent_id(agent_service: AgentService, identifier: str) -> UUID | None:
    """Resolve a UUID for an agent referenced by UUID *or* slug.

    Returns the agent's UUID if found in the caller's workspace, else None.
    """
    with suppress(ValueError):
        return UUID(identifier)
    agent = await agent_service.get_by_slug(identifier)
    if agent:
        return agent.id
    # Built-in catalog agents aren't in the tenant table; resolve by projected slug.
    catalog_agent = await agent_service.get_catalog_by_slug(identifier)
    return catalog_agent.id if catalog_agent else None


async def _grant_agent_owner(agent_id: UUID | str, user_id: str, workspace_id: str) -> None:
    """Assert that ``user_id`` owns ``agent_id`` in the resource graph.

    Called on every path that materializes an agent the caller now owns —
    create, catalog install (copy-on-write fork), and edit (which forks an
    un-owned catalog agent) — so a freshly-minted agent never ends up without
    its ownership relationships (which would 403 the creator on their own row).
    Attaches the agent artifact to the workspace root project and grants the
    creator read/write/manage. Writes are idempotent, so re-asserting on update
    is harmless.
    """
    await grant_resource_owner(
        resource_id=agent_id,
        workspace_id=workspace_id,
        user_id=user_id,
    )


async def _overlay_approval_flags(
    session: AsyncSession,
    user_context: UserContext,
    responses: list[AgentResponse],
) -> None:
    """Reconstitute each response's approval flags from rules for the UI."""
    agent_ids = [response.id for response in responses]
    by_agent = await approval_targets_for_agents(session, user_context, agent_ids)
    for response in responses:
        targets = by_agent.get(response.id)
        if not targets or not response.tools:
            continue
        applied = apply_approval_targets([t.model_dump() for t in response.tools], targets)
        response.tools = [TOOL_CONFIG_ADAPTER.validate_python(t) for t in applied]


@router.post("/", response_model=AgentResponse)
async def create_agent(
    data: AgentCreate,
    user_context: UserContextDep,
    session: DatabaseSessionDep,
    agent_service: AgentService = Depends(get_agent_service),
):
    """Create a new agent."""
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

    agent = await agent_service.create_agent(data)
    await _grant_agent_owner(agent.id, user_context.user_id, user_context.workspace_id)
    response = AgentResponse.from_domain(agent)
    await _overlay_approval_flags(session, user_context, [response])
    return response


class ToolResponse(BaseModel):
    """Unified tool response format."""

    name: str
    type: Literal["code", "mcp"]
    description: str
    input_schema: dict[str, Any]
    mcp_instance_id: UUID | None = None
    mcp_instance_name: str | None = None


def _mcp_tool_response(tool: dict[str, Any], instance) -> ToolResponse | None:
    """Normalize persisted MCP tool metadata to the public tool response."""
    raw_function = tool.get("function")
    function = raw_function if isinstance(raw_function, dict) else tool
    name = function.get("name")
    if not name:
        return None
    return ToolResponse(
        name=name,
        type="mcp",
        description=function.get("description") or f"MCP tool: {name}",
        input_schema=function.get("parameters") or function.get("inputSchema") or {},
        mcp_instance_id=instance.id,
        mcp_instance_name=instance.name,
    )


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
                    if response := _mcp_tool_response(tool, instance):
                        tools.append(response)
        else:
            instances = await mcp_service.list()
            for instance in instances:
                mcp_tools = instance.get_available_tools()
                for tool in mcp_tools:
                    if response := _mcp_tool_response(tool, instance):
                        tools.append(response)

    return tools


@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(
    agent_id: str,
    user_context: UserContextDep,
    session: DatabaseSessionDep,
    agent_service: AgentService = Depends(get_read_agent_service),
):
    """Get an agent by UUID or workspace-scoped slug (tenant or catalog)."""
    resolved_id = await _resolve_agent_id(agent_service, agent_id)
    if not resolved_id:
        raise HTTPException(status_code=404, detail="Agent not found")
    agent = await agent_service.get_with_skills(resolved_id)
    if not agent:
        # Fall back to a read-only catalog projection (no DB row materialized).
        agent = await agent_service.get_with_catalog(resolved_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    response = AgentResponse.from_domain(agent, include_skills=True)
    await _overlay_approval_flags(session, user_context, [response])
    return response


@router.post("/{agent_id}/install", response_model=AgentResponse)
async def install_agent(
    agent_id: str,
    user_context: UserContextDep,
    agent_service: AgentService = Depends(get_agent_service),
):
    """Add a built-in catalog agent to the workspace (copy-on-write fork).

    Resolves a catalog agent by UUID or slug and materializes a tenant copy.
    Idempotent: returns the existing workspace copy if already installed.
    """
    resolved_id = await _resolve_agent_id(agent_service, agent_id)
    if not resolved_id:
        raise HTTPException(status_code=404, detail="Agent not found")
    agent = await agent_service.install_catalog_agent(resolved_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    # The fork created a real tenant row; assert ownership so it is not orphaned
    # in Keto (matching create). Idempotent if the workspace already installed it.
    await _grant_agent_owner(agent.id, user_context.user_id, user_context.workspace_id)
    agent = await agent_service.get_with_skills(agent.id) or agent
    return AgentResponse.from_domain(agent, include_skills=True)


@router.get("", response_model=list[AgentResponse])
@router.get("/", response_model=list[AgentResponse])
async def list_agents(
    user_context: UserContextDep,
    session: DatabaseSessionDep,
    agent_service: AgentService = Depends(get_read_agent_service),
):
    """List all workspace agents.

    Access Control:
        Returns all agents within the current user's workspace (workspace isolation).
        All users in the same workspace can see all workspace agents.

        Note: User-level access control should be implemented via authorization
        layer (future access-control) rather than query parameters.
    """
    agents = await agent_service.list()
    responses = [AgentResponse.from_domain(agent) for agent in agents]
    await _overlay_approval_flags(session, user_context, responses)
    return responses


@router.patch("/{agent_id}", response_model=AgentResponse)
async def update_agent(
    agent_id: str,
    data: AgentUpdate,
    user_context: UserContextDep,
    session: DatabaseSessionDep,
    agent_service: AgentService = Depends(get_agent_service),
):
    """Update an agent (by UUID or workspace-scoped slug)."""
    resolved_id = await _resolve_agent_id(agent_service, agent_id)
    if not resolved_id:
        raise HTTPException(status_code=404, detail="Agent not found")
    await require_permission("edit", "agent", str(resolved_id), user_context.user_id)
    agent = await agent_service.update_agent(id=resolved_id, payload=data)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    # Editing an un-installed catalog agent forks a tenant copy (copy-on-write);
    # assert ownership of the resulting row. Idempotent for plain edits.
    await _grant_agent_owner(agent.id, user_context.user_id, user_context.workspace_id)
    agent = await agent_service.get_with_skills(agent.id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    response = AgentResponse.from_domain(agent, include_skills=True)
    await _overlay_approval_flags(session, user_context, [response])
    return response


@router.delete("/{agent_id}")
async def delete_agent(
    agent_id: str,
    user_context: UserContextDep,
    agent_service: AgentService = Depends(get_agent_service),
):
    """Delete an agent (by UUID or workspace-scoped slug)."""
    resolved_id = await _resolve_agent_id(agent_service, agent_id)
    if not resolved_id:
        raise HTTPException(status_code=404, detail="Agent not found")
    await require_permission("delete", "agent", str(resolved_id), user_context.user_id)
    success = await agent_service.delete_agent(resolved_id)
    if not success:
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"status": "success"}


# Include A2A protocol subroutes
router.include_router(agents_a2a.router, prefix="/{agent_id}", tags=["agents-a2a"])

# Include agent-specific well-known subroutes
router.include_router(agents_well_known.router, prefix="/{agent_id}", tags=["agents-well-known"])
