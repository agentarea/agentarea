"""Agent-specific well-known endpoints for A2A protocol.

This module provides well-known endpoints for individual agents.
Each agent gets its own /.well-known/agent.json endpoint at
/v1/agents/{agent_id}/.well-known/agent.json

This allows for proper A2A compliance where each agent can be discovered
individually, and later can be proxied to subdomains
(agent1.domain.com -> /v1/agents/{id}/.well-known/)
"""

import logging
from uuid import UUID

from agentarea_agents.domain.models import Agent
from agentarea_common.infrastructure.database import get_read_db_session
from agentarea_common.utils.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentProvider,
    AgentSkill,
)
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Create subrouter for agent-specific well-known endpoints
router = APIRouter()


def get_base_url(request: Request) -> str:
    """Get base URL from request."""
    return f"{request.url.scheme}://{request.url.netloc}"


async def get_public_agent(agent_id: UUID, session: AsyncSession) -> Agent | None:
    """Read an agent for public discovery without requiring workspace auth."""
    result = await session.execute(select(Agent).where(Agent.id == agent_id))
    return result.scalar_one_or_none()


async def create_agent_card_for_agent(agent, base_url: str, agent_id: UUID) -> AgentCard:
    """Create A2A AgentCard for specific agent."""
    # Advertise A2UI extension if agent supports it
    extensions = None
    if getattr(agent, "a2ui_enabled", False):
        extensions = [
            {
                "uri": "https://a2ui.org/a2a-extension/a2ui/v0.9",
                "params": {
                    "supportedCatalogIds": [
                        "https://a2ui.org/specification/v0_9/basic_catalog.json"
                    ],
                },
            }
        ]

    rpc_url = f"{base_url}/v1/agents/{agent_id}/a2a/rpc"
    return AgentCard(
        name=agent.name,
        description=agent.description or f"AI agent {agent.name}",
        supportedInterfaces=[
            AgentInterface(url=rpc_url, protocolBinding="JSONRPC", protocolVersion="1.0")
        ],
        version="1.0.0",
        documentationUrl=f"{base_url}/v1/agents/{agent_id}/.well-known/a2a-info.json",
        capabilities=AgentCapabilities(
            streaming=True,
            pushNotifications=True,
            extendedAgentCard=True,
            extensions=extensions,
        ),
        provider=AgentProvider(organization="AgentArea", url=base_url),
        defaultInputModes=["text/plain", "application/json"],
        defaultOutputModes=["text/plain", "application/json"],
        securitySchemes={
            "bearer": {
                "type": "http",
                "scheme": "bearer",
            }
        },
        security=[{"bearer": []}],
        skills=[
            AgentSkill(
                id="text-processing",
                name="Text Processing",
                description=f"Process and respond to text messages using {agent.name}",
                tags=["text", "chat"],
                inputModes=["text/plain"],
                outputModes=["text/plain"],
            )
        ],
    )


@router.get("/.well-known/agent.json")
@router.get("/.well-known/agent-card.json")
async def get_agent_well_known_card(
    agent_id: UUID,
    request: Request,
    db_session: AsyncSession = Depends(get_read_db_session),
) -> AgentCard:
    """Agent-specific well-known discovery endpoint.

    Returns the agent card for this specific agent.
    This endpoint can be accessed at:
    - /v1/agents/{agent_id}/.well-known/agent-card.json
    - /v1/agents/{agent_id}/.well-known/agent.json (legacy alias)

    This allows each agent to have its own well-known endpoint, which is A2A compliant.
    Later, this can be proxied to subdomains:
    - agent1.domain.com/.well-known/agent.json -> /v1/agents/{id}/.well-known/agent.json
    """
    try:
        # Get the specific agent
        agent = await get_public_agent(agent_id, db_session)
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

        base_url = get_base_url(request)

        # Create agent card for this specific agent
        agent_card = await create_agent_card_for_agent(agent, base_url, agent_id)

        logger.info(f"Agent well-known discovery: {agent.name} ({agent_id})")
        return agent_card

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in agent well-known discovery for {agent_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Agent discovery failed") from e


@router.get("/.well-known/a2a-info.json")
async def get_agent_a2a_info(
    agent_id: UUID,
    request: Request,
    db_session: AsyncSession = Depends(get_read_db_session),
) -> dict:
    """Agent-specific A2A protocol information.

    Provides A2A protocol information specific to this agent.
    """
    try:
        # Verify agent exists
        agent = await get_public_agent(agent_id, db_session)
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

        base_url = get_base_url(request)

        return {
            "protocol": "A2A",
            "version": "1.0.0",
            "server": "AgentArea",
            "agent": {
                "id": str(agent_id),
                "name": agent.name,
                "description": agent.description,
                "status": agent.status,
            },
            "compliance": {
                "a2a_specification": "https://a2aproject.github.io/A2A/latest/specification/",
                "rfc_8615": "https://tools.ietf.org/html/rfc8615",
                "json_rpc": "https://www.jsonrpc.org/specification/v2",
            },
            "endpoints": {
                "agent_card": f"{base_url}/v1/agents/{agent_id}/.well-known/agent-card.json",
                "legacy_agent_card": f"{base_url}/v1/agents/{agent_id}/.well-known/agent.json",
                "rpc": f"{base_url}/v1/agents/{agent_id}/rpc",
                "stream": f"{base_url}/v1/agents/{agent_id}/stream",
                "tasks": f"{base_url}/v1/agents/{agent_id}/tasks/",
            },
            "future_subdomain": f"agent-{agent_id}.{request.url.hostname}",
            "subdomain_note": "This agent will be available at its own subdomain in the future",
            "supported_methods": [
                "SendMessage",
                "SendStreamingMessage",
                "GetTask",
                "CancelTask",
                "SubscribeToTask",
                "ListTasks",
                "CreateTaskPushNotificationConfig",
                "GetTaskPushNotificationConfig",
                "ListTaskPushNotificationConfigs",
                "DeleteTaskPushNotificationConfig",
                "GetExtendedAgentCard",
            ],
            "capabilities": {
                "streaming": True,
                "pushNotifications": True,
                "extendedAgentCard": True,
            },
            "authentication": {
                "supported": True,
                "methods": ["bearer", "api_key"],
                "required": False,
            },
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting A2A info for agent {agent_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="A2A info failed") from e


@router.get("/.well-known/")
async def get_agent_well_known_index(
    agent_id: UUID,
    request: Request,
    db_session: AsyncSession = Depends(get_read_db_session),
) -> dict:
    """Agent-specific well-known endpoints index."""
    try:
        # Verify agent exists
        agent = await get_public_agent(agent_id, db_session)
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

        base_url = get_base_url(request)

        return {
            "message": f"A2A Protocol Well-Known Endpoints for {agent.name}",
            "agent": {"id": str(agent_id), "name": agent.name, "description": agent.description},
            "endpoints": {
                "agent-card.json": f"{base_url}/v1/agents/{agent_id}/.well-known/agent-card.json",
                "agent.json": f"{base_url}/v1/agents/{agent_id}/.well-known/agent.json",
                "a2a-info.json": f"{base_url}/v1/agents/{agent_id}/.well-known/a2a-info.json",
            },
            "specification": "https://a2aproject.github.io/A2A/latest/specification/",
            "rfc": "https://tools.ietf.org/html/rfc8615",
            "note": "This agent-specific well-known endpoint can be proxied to a subdomain",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting well-known index for agent {agent_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Well-known index failed") from e
