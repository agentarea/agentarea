"""Network topology API for organizational overview."""

from __future__ import annotations

import logging
from typing import Any, Literal

from agentarea_common.auth import UserContextDep
from agentarea_common.di.container import get_container
from agentarea_common.features.service import FeatureService
from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import selectinload

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/network", tags=["network"])


# --- Response Models ---


class NetworkNode(BaseModel):
    id: str
    type: Literal["agent", "mcp_instance", "skill", "trigger"]
    label: str
    status: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class NetworkEdge(BaseModel):
    id: str
    source: str
    target: str
    relation: str


class GovernanceOverlay(BaseModel):
    interceptor_name: str
    category: str
    phases: list[str]


class NetworkTopologyResponse(BaseModel):
    nodes: list[NetworkNode]
    edges: list[NetworkEdge]
    governance: list[GovernanceOverlay]
    deployment_mode: str = "oss"


# --- Helpers ---


_GOVERNANCE_INTERCEPTORS = [
    GovernanceOverlay(
        interceptor_name="capability_guard", category="gate", phases=["pre_tool_call"]
    ),
    GovernanceOverlay(
        interceptor_name="cost_budget_guard", category="gate", phases=["pre_llm_call"]
    ),
    GovernanceOverlay(
        interceptor_name="token_budget_guard", category="gate", phases=["pre_llm_call"]
    ),
    GovernanceOverlay(
        interceptor_name="escalation_guard", category="gate", phases=["pre_tool_call"]
    ),
    GovernanceOverlay(
        interceptor_name="semantic_guard", category="gate", phases=["pre_llm_call", "pre_tool_call"]
    ),
    GovernanceOverlay(
        interceptor_name="prompt_injection_detector",
        category="filter",
        phases=["pre_llm_call", "post_llm_call"],
    ),
    GovernanceOverlay(
        interceptor_name="output_sanitizer", category="filter", phases=["post_llm_call"]
    ),
    GovernanceOverlay(
        interceptor_name="content_policy_enforcer",
        category="filter",
        phases=["pre_llm_call", "post_llm_call"],
    ),
    GovernanceOverlay(
        interceptor_name="mcp_tool_scanner",
        category="filter",
        phases=["tool_discovery", "pre_tool_call"],
    ),
    GovernanceOverlay(
        interceptor_name="audit_observer",
        category="observer",
        phases=["pre_llm_call", "post_llm_call", "pre_tool_call", "post_tool_call"],
    ),
    GovernanceOverlay(
        interceptor_name="metrics_observer",
        category="observer",
        phases=["pre_llm_call", "post_llm_call", "pre_tool_call", "post_tool_call"],
    ),
]


# --- Endpoint ---


@router.get("/topology", response_model=NetworkTopologyResponse)
async def get_network_topology(
    user_context: UserContextDep,
) -> NetworkTopologyResponse:
    """Get the full network topology for the current workspace.

    Returns all agents, skills, MCP instances, and triggers as nodes,
    with edges representing their relationships.

    Each entity type is fetched in its own DB session so the four queries
    can run concurrently via ``asyncio.gather`` without sharing a single
    async session (which is not safe for concurrent use).
    """
    import asyncio

    from agentarea_agents.domain.models import Agent
    from agentarea_agents.domain.skill_models import Skill, skill_members_table
    from agentarea_common.infrastructure.database import db

    accessible_workspaces = user_context.accessible_workspaces or [user_context.workspace_id]

    # --- Parallel fetches, each with its own session ---

    async def fetch_agents() -> list:
        async with db.session() as session:
            query = (
                select(Agent)
                .where(Agent.workspace_id.in_(accessible_workspaces))
                .options(selectinload(Agent.skills))
            )
            result = await session.execute(query)
            return list(result.scalars().all())

    async def fetch_skills() -> tuple[list, list]:
        async with db.session() as session:
            # Skills within accessible workspaces
            skill_query = select(Skill).where(Skill.workspace_id.in_(accessible_workspaces))
            skill_result = await session.execute(skill_query)
            skills = list(skill_result.scalars().all())

            # Skill → Skill membership edges (scoped to accessible workspaces)
            members = []
            try:
                workspace_skill_ids = select(Skill.id).where(
                    Skill.workspace_id.in_(accessible_workspaces)
                )
                member_query = select(skill_members_table).where(
                    skill_members_table.c.parent_skill_id.in_(workspace_skill_ids)
                )
                member_result = await session.execute(member_query)
                members = list(member_result)
            except Exception as e:
                logger.debug(f"Could not fetch skill members: {e}")

            return skills, members

    async def fetch_mcp_instances() -> list:
        try:
            from agentarea_common.base import RepositoryFactory
            from agentarea_mcp.infrastructure.repository import MCPServerInstanceRepository

            async with db.session() as session:
                repo = RepositoryFactory(session, user_context).create_repository(
                    MCPServerInstanceRepository
                )
                return await repo.list_all()
        except Exception as e:
            logger.warning(f"Failed to fetch MCP instances: {e}")
            return []

    async def fetch_triggers() -> list:
        try:
            from agentarea_triggers.infrastructure.orm import TriggerORM

            async with db.session() as session:
                query = select(TriggerORM).where(TriggerORM.workspace_id.in_(accessible_workspaces))
                result = await session.execute(query)
                return list(result.scalars().all())
        except Exception as e:
            logger.warning(f"Failed to fetch triggers: {e}")
            return []

    agents, (skills, skill_members), mcp_instances, triggers = await asyncio.gather(
        fetch_agents(),
        fetch_skills(),
        fetch_mcp_instances(),
        fetch_triggers(),
    )

    nodes: list[NetworkNode] = []
    edges: list[NetworkEdge] = []

    # --- Build agent nodes ---
    for agent in agents:
        agent_id = str(agent.id)

        skills_data = []
        if hasattr(agent, "skills") and agent.skills:
            skills_data = [
                {"id": str(skill.id), "name": skill.name}
                for skill in agent.skills
            ]

        tools_config = None
        if hasattr(agent, "tools_config") and agent.tools_config:
            tools_config = agent.tools_config
        elif hasattr(agent, "tools") and agent.tools:
            tools_config = agent.tools if isinstance(agent.tools, dict) else None

        model_info = None
        if hasattr(agent, "model_info") and agent.model_info:
            model_info = {
                "provider_name": getattr(agent.model_info, "provider_name", None),
                "model_display_name": getattr(agent.model_info, "model_display_name", None),
                "config_name": getattr(agent.model_info, "config_name", None),
            }
            model_info = {k: v for k, v in model_info.items() if v is not None}
            if not model_info:
                model_info = None

        nodes.append(
            NetworkNode(
                id=agent_id,
                type="agent",
                label=agent.name,
                status=getattr(agent, "status", None),
                metadata={
                    k: v
                    for k, v in {
                        "model_id": getattr(agent, "model_id", None),
                        "description": getattr(agent, "description", None),
                        "skills": skills_data if skills_data else None,
                        "tools_config": tools_config,
                        "model_info": model_info,
                    }.items()
                    if v is not None
                },
            )
        )

        # Agent → Skill edges (eagerly loaded via selectinload)
        for skill in agent.skills:
            edges.append(
                NetworkEdge(
                    id=f"{agent_id}-{skill.id}-has_skill",
                    source=agent_id,
                    target=str(skill.id),
                    relation="has_skill",
                )
            )

        # Agent → MCP edges (via agent.tools JSON field)
        if agent.tools:
            tools_data = (
                agent.tools
                if isinstance(agent.tools, list)
                else agent.tools.get("tools", [])
                if isinstance(agent.tools, dict)
                else []
            )
            seen_servers: set[str] = set()
            for tool in tools_data:
                if isinstance(tool, dict):
                    server_id = (
                        tool.get("tool_server_id")
                        or tool.get("server_id")
                        or tool.get("mcp_instance_id")
                    )
                    if server_id and str(server_id) not in seen_servers:
                        seen_servers.add(str(server_id))
                        edges.append(
                            NetworkEdge(
                                id=f"{agent_id}-{server_id}-uses_mcp",
                                source=agent_id,
                                target=str(server_id),
                                relation="uses_mcp",
                            )
                        )

    # --- Build skill nodes ---
    for skill in skills:
        nodes.append(
            NetworkNode(
                id=str(skill.id),
                type="skill",
                label=skill.name,
                metadata={
                    k: v
                    for k, v in {
                        "source_type": getattr(skill, "source_type", None),
                        "description": getattr(skill, "description", None),
                        "network_scope": skill.network_scope,
                    }.items()
                    if v is not None
                },
            )
        )

    # --- Skill → Skill edges (bundle membership: child is member_of parent) ---
    for row in skill_members:
        parent_id = str(row.parent_skill_id)
        child_id = str(row.child_skill_id)
        edges.append(
            NetworkEdge(
                id=f"{child_id}-{parent_id}-member_of",
                source=child_id,
                target=parent_id,
                relation="member_of",
            )
        )

    # --- Build MCP instance nodes ---
    for instance in mcp_instances:
        instance_id = str(instance.id)
        nodes.append(
            NetworkNode(
                id=instance_id,
                type="mcp_instance",
                label=getattr(instance, "name", None) or getattr(instance, "slug", instance_id),
                status=getattr(instance, "status", None),
                metadata={
                    k: v
                    for k, v in {
                        "tool_count": len(instance.get_available_tools()),
                        "network_scope": instance.network_scope,
                    }.items()
                    if v is not None
                },
            )
        )

    # --- Build trigger nodes ---
    for trigger in triggers:
        trigger_id = str(trigger.id)
        nodes.append(
            NetworkNode(
                id=trigger_id,
                type="trigger",
                label=getattr(trigger, "name", trigger_id),
                status="active" if getattr(trigger, "is_active", False) else "inactive",
                metadata={
                    k: v
                    for k, v in {
                        "trigger_type": getattr(
                            getattr(trigger, "trigger_type", None),
                            "value",
                            str(getattr(trigger, "trigger_type", "unknown")),
                        ),
                    }.items()
                    if v is not None
                },
            )
        )

        # Agent → Trigger edge
        agent_id_val = getattr(trigger, "agent_id", None)
        if agent_id_val:
            edges.append(
                NetworkEdge(
                    id=f"{agent_id_val!s}-{trigger_id}-has_trigger",
                    source=str(agent_id_val),
                    target=trigger_id,
                    relation="has_trigger",
                )
            )

    # Governance overlay and deployment mode from FeatureService (DI singleton)
    feature_service = get_container().get(FeatureService)
    governance: list[GovernanceOverlay] = []
    if feature_service.show_governance_overlay:
        governance = list(_GOVERNANCE_INTERCEPTORS)

    return NetworkTopologyResponse(
        nodes=nodes,
        edges=edges,
        governance=governance,
        deployment_mode=feature_service.mode.value,
    )
