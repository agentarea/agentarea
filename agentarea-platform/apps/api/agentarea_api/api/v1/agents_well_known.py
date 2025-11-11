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

from agentarea_agents.application.agent_service import AgentService
from agentarea_api.api.deps.services import get_agent_service
from agentarea_common.utils.types import AgentCapabilities, AgentCard, AgentProvider, AgentSkill
from fastapi import APIRouter, Depends, HTTPException, Request

logger = logging.getLogger(__name__)

# Create subrouter for agent-specific well-known endpoints
router = APIRouter()


def get_base_url(request: Request) -> str:
    """Get base URL from request."""
    return f"{request.url.scheme}://{request.url.netloc}"


async def create_agent_card_for_agent(agent, base_url: str, agent_id: UUID) -> AgentCard:
    """Create A2A AgentCard for specific agent."""
    return AgentCard(
        name=agent.name,
        description=agent.description,
        url=f"{base_url}/v1/agents/{agent_id}/rpc",  # Agent-specific RPC endpoint
        version="1.0.0",
        documentation_url=f"{base_url}/v1/agents/{agent_id}/.well-known/a2a-info.json",
        capabilities=AgentCapabilities(
            streaming=True, pushNotifications=False, stateTransitionHistory=True
        ),
        provider=AgentProvider(organization="AgentArea"),
        skills=[
            AgentSkill(
                id="text-processing",
                name="Text Processing",
                description=f"Process and respond to text messages using {agent.name}",
                inputModes=["text"],
                outputModes=["text"],
            )
        ],
    )


@router.get("/.well-known/agent.json")
async def get_agent_well_known_card(
    agent_id: UUID,
    request: Request,
    agent_service: AgentService = Depends(get_agent_service),
) -> AgentCard:
    """Agent-specific well-known discovery endpoint.

    Returns the agent card for this specific agent.
    This endpoint can be accessed at: /v1/agents/{agent_id}/.well-known/agent.json

    This allows each agent to have its own well-known endpoint, which is A2A compliant.
    Later, this can be proxied to subdomains:
    - agent1.domain.com/.well-known/agent.json -> /v1/agents/{id}/.well-known/agent.json
    """
    try:
        # Get the specific agent
        agent = await agent_service.get(agent_id)
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
    agent_service: AgentService = Depends(get_agent_service),
) -> dict:
    """Agent-specific A2A protocol information.

    Provides A2A protocol information specific to this agent.
    """
    try:
        # Verify agent exists
        agent = await agent_service.get(agent_id)
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
                "agent_card": f"{base_url}/v1/agents/{agent_id}/.well-known/agent.json",
                "rpc": f"{base_url}/v1/agents/{agent_id}/rpc",
                "stream": f"{base_url}/v1/agents/{agent_id}/stream",
                "tasks": f"{base_url}/v1/agents/{agent_id}/tasks/",
            },
            "future_subdomain": f"agent-{agent_id}.{request.url.hostname}",
            "subdomain_note": "This agent will be available at its own subdomain in the future",
            "supported_methods": [
                "message/send",
                "message/stream",
                "tasks/get",
                "tasks/cancel",
                "agent/authenticatedExtendedCard",
            ],
            "capabilities": {
                "streaming": True,
                "pushNotifications": False,
                "stateTransitionHistory": True,
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
    agent_service: AgentService = Depends(get_agent_service),
) -> dict:
    """Agent-specific well-known endpoints index."""
    try:
        # Verify agent exists
        agent = await agent_service.get(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

        base_url = get_base_url(request)

        return {
            "message": f"A2A Protocol Well-Known Endpoints for {agent.name}",
            "agent": {"id": str(agent_id), "name": agent.name, "description": agent.description},
            "endpoints": {
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
