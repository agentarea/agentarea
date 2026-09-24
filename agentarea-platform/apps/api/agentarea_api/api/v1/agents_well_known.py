"""Agent-specific well-known endpoints for A2A protocol.

This module provides well-known endpoints for individual agents.
Each agent gets its own /.well-known/agent-card.json endpoint at
/v1/agents/{agent_id}/.well-known/agent-card.json

This allows for proper A2A compliance where each agent can be discovered
individually, and later can be proxied to subdomains
(agent1.domain.com -> /v1/agents/{id}/.well-known/)
"""

import logging
from uuid import UUID

from agentarea_agents.domain.models import Agent
from agentarea_api.api.v1.a2a_card import agent_card_json, build_agent_card, get_base_url
from agentarea_common.auth.route_authz import unrestricted
from agentarea_common.config.database import get_read_db_session
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Create subrouter for agent-specific well-known endpoints
router = APIRouter()


async def get_public_agent(agent_id: UUID, session: AsyncSession) -> Agent | None:
    """Read an agent for public discovery without requiring workspace auth."""
    result = await session.execute(select(Agent).where(Agent.id == agent_id))
    return result.scalar_one_or_none()


async def public_agent_card_response(
    agent_id: UUID, request: Request, db_session: AsyncSession
) -> JSONResponse:
    """The agent's public A2A card as protocol JSON; 404 when the agent is unknown."""
    agent = await get_public_agent(agent_id, db_session)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
    card = build_agent_card(
        agent, base_url=get_base_url(request), agent_id=agent_id, extended=False
    )
    logger.info(f"Agent well-known discovery: {agent.name} ({agent_id})")
    return JSONResponse(agent_card_json(card))


@router.get(
    "/.well-known/agent-card.json",
    response_model=None,
    dependencies=[
        unrestricted("public agent discovery document, served unauthenticated by design")
    ],
)
async def get_agent_well_known_card(
    agent_id: UUID,
    request: Request,
    db_session: AsyncSession = Depends(get_read_db_session),
) -> JSONResponse:
    """Agent-specific well-known discovery endpoint.

    Returns the agent card for this specific agent, at
    /v1/agents/{agent_id}/.well-known/agent-card.json

    This allows each agent to have its own well-known endpoint, which is A2A compliant.
    Later, this can be proxied to subdomains:
    - agent1.domain.com/.well-known/agent-card.json -> /v1/agents/{id}/.well-known/agent-card.json
    """
    return await public_agent_card_response(agent_id, request, db_session)


@router.get(
    "/.well-known/a2a-info.json",
    dependencies=[
        unrestricted("public agent discovery document, served unauthenticated by design")
    ],
)
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


@router.get(
    "/.well-known/",
    dependencies=[
        unrestricted("public agent discovery document, served unauthenticated by design")
    ],
)
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
