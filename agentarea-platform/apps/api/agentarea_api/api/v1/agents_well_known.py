"""Agent-specific well-known endpoints for A2A protocol, under the API host.

An agent's canonical address is its own host (``A2A_AGENT_URL``), whose root
carries the card; see :mod:`agentarea_api.api.v1.agents_a2a`. These routes
serve the same agent at ``/v1/agents/{agent_id}/.well-known/...`` for clients
configured with the API host.
"""

import logging
from uuid import UUID

from agentarea_agents.domain.models import Agent
from agentarea_api.api.v1.a2a_card import (
    agent_card_json,
    agent_rpc_url,
    build_agent_card,
)
from agentarea_common.auth.route_authz import unrestricted
from agentarea_common.base.tenant_scope import unscoped
from agentarea_common.config import get_settings
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
    with unscoped("a discovery URL names an agent, not a workspace; the agent's decides"):
        result = await session.execute(select(Agent).where(Agent.id == agent_id))
    return result.scalar_one_or_none()


async def public_agent_card_response(
    agent_id: UUID, db_session: AsyncSession, *, rpc_url: str
) -> JSONResponse:
    """The agent's public A2A card as protocol JSON; 404 when the agent is unknown."""
    agent = await get_public_agent(agent_id, db_session)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
    card = build_agent_card(agent, rpc_url=rpc_url, extended=False)
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
    """The agent card under the API host; its endpoint is on the API host too."""
    return await public_agent_card_response(agent_id, db_session, rpc_url=agent_rpc_url(agent_id))


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

        base_url = get_settings().app.API_BASE_URL.rstrip("/")

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
            "a2a_url": get_settings().app.a2a_agent_url(agent_id),
            "endpoints": {
                "agent_card": f"{base_url}/v1/agents/{agent_id}/.well-known/agent-card.json",
                "rpc": agent_rpc_url(agent_id),
            },
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

        base_url = get_settings().app.API_BASE_URL.rstrip("/")

        return {
            "message": f"A2A Protocol Well-Known Endpoints for {agent.name}",
            "agent": {"id": str(agent_id), "name": agent.name, "description": agent.description},
            "endpoints": {
                "agent-card.json": f"{base_url}/v1/agents/{agent_id}/.well-known/agent-card.json",
                "a2a-info.json": f"{base_url}/v1/agents/{agent_id}/.well-known/a2a-info.json",
            },
            "specification": "https://a2aproject.github.io/A2A/latest/specification/",
            "rfc": "https://tools.ietf.org/html/rfc8615",
            "a2a_url": get_settings().app.a2a_agent_url(agent_id),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting well-known index for agent {agent_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Well-known index failed") from e
