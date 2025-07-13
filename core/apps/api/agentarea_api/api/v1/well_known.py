"""Well-known endpoints for A2A protocol agent discovery.

This module implements RFC 8615 well-known URIs for agent discovery.
Standard A2A protocol discovery endpoints:
- /.well-known/agent.json - Single agent discovery
- /.well-known/agents.json - Multi-agent discovery (custom extension)
"""

import logging
from typing import List
from uuid import UUID

from agentarea_agents.application.agent_service import AgentService
from agentarea_api.api.deps.services import get_agent_service
from agentarea_common.utils.types import AgentCard, AgentCapabilities, AgentProvider, AgentSkill
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/.well-known", tags=["well-known"])


class AgentRegistry(BaseModel):
    """Registry of all available agents (NON-STANDARD EXTENSION)."""
    agents: List[AgentCard]
    total_count: int
    discovery_url: str
    version: str = "1.0.0"
    warning: str = "This is a non-standard extension to A2A protocol"


def get_base_url(request: Request) -> str:
    """Get base URL from request."""
    return f"{request.url.scheme}://{request.url.netloc}"


async def create_agent_card(agent, base_url: str) -> AgentCard:
    """Create A2A AgentCard from database agent."""
    return AgentCard(
        name=agent.name,
        description=agent.description,
        url=f"{base_url}/v1/agents/{agent.id}/rpc",
        version="1.0.0",
        documentation_url=f"{base_url}/v1/agents/{agent.id}/.well-known/a2a-info.json",
        capabilities=AgentCapabilities(
            streaming=True,
            pushNotifications=False,
            stateTransitionHistory=True
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


@router.get("/agent.json")
async def get_agent_card_by_subdomain(
    request: Request,
    agent_id: UUID | None = Query(None, description="Specific agent ID to discover"),
    agent_service: AgentService = Depends(get_agent_service),
) -> AgentCard:
    """Standard A2A agent discovery endpoint (RFC 8615).
    
    Per A2A specification:
    - Each agent should have its own domain/subdomain (e.g., agent1.yourapp.com)
    - /.well-known/agent.json should return the agent card for that specific domain
    - Multi-agent discovery should be done via external registries, not well-known URIs
    
    This implementation supports:
    1. Subdomain-based discovery (recommended)
    2. Query parameter fallback (for development)
    3. Default agent fallback (for single-agent deployments)
    """
    try:
        base_url = get_base_url(request)
        host = request.headers.get("host", "").lower()
        
        # Try to extract agent ID from subdomain
        # Format: agent-{uuid}.yourapp.com or {agent-name}.yourapp.com
        agent_from_subdomain = None
        if "." in host:
            subdomain = host.split(".")[0]
            
            # Try UUID format: agent-{uuid}
            if subdomain.startswith("agent-"):
                try:
                    agent_uuid_str = subdomain[6:]  # Remove "agent-" prefix
                    agent_uuid = UUID(agent_uuid_str)
                    agent_from_subdomain = await agent_service.get(agent_uuid)
                except ValueError:
                    pass
            
            # Try name-based subdomain lookup
            if not agent_from_subdomain:
                agents = await agent_service.list()
                for agent in agents:
                    # Convert agent name to subdomain format
                    agent_subdomain = agent.name.lower().replace(" ", "-").replace("_", "-")
                    if subdomain == agent_subdomain:
                        agent_from_subdomain = agent
                        break
        
        # Priority order: subdomain > query param > main domain agent
        target_agent = None
        
        if agent_from_subdomain:
            target_agent = agent_from_subdomain
            logger.info(f"Agent discovered via subdomain: {host}")
        elif agent_id:
            target_agent = await agent_service.get(agent_id)
            if not target_agent:
                raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
            logger.info(f"Agent discovered via query parameter: {agent_id}")
        else:
            # Main domain agent (designated primary agent)
            agents = await agent_service.list()
            if not agents:
                raise HTTPException(
                    status_code=404, 
                    detail="No agents available for discovery"
                )
            
            # Try to find agent marked as "primary" or "main", otherwise use first
            main_agent = None
            for agent in agents:
                # Check if agent is marked as primary/main in metadata or name
                if (agent.name.lower() in ["main", "primary", "default"] or 
                    "primary" in agent.description.lower() or
                    "main" in agent.description.lower()):
                    main_agent = agent
                    break
            
            target_agent = main_agent or agents[0]  # Fallback to first agent
            logger.info(f"Using main domain agent: {target_agent.name} ({target_agent.id})")
        
        return await create_agent_card(target_agent, base_url)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in well-known agent discovery: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Agent discovery failed")


@router.get("/agents.json")
async def get_agent_registry(
    request: Request,
    limit: int = Query(10, ge=1, le=100, description="Maximum number of agents to return"),
    offset: int = Query(0, ge=0, description="Number of agents to skip"),
    agent_service: AgentService = Depends(get_agent_service),
) -> AgentRegistry:
    """Multi-agent discovery endpoint (NON-STANDARD EXTENSION).
    
    ⚠️  WARNING: This is NOT part of the A2A protocol specification.
    The A2A standard defines /.well-known/agent.json for single-agent discovery.
    Multi-agent discovery should be done via external registries/catalogs.
    
    This endpoint is provided for convenience but may not be compatible with
    standard A2A tooling. Use at your own risk.
    """
    try:
        base_url = get_base_url(request)
        
        # Get all agents
        all_agents = await agent_service.list()
        total_count = len(all_agents)
        
        # Apply pagination
        paginated_agents = all_agents[offset:offset + limit]
        
        # Convert to agent cards
        agent_cards = []
        for agent in paginated_agents:
            agent_card = await create_agent_card(agent, base_url)
            agent_cards.append(agent_card)
        
        return AgentRegistry(
            agents=agent_cards,
            total_count=total_count,
            discovery_url=f"{base_url}/.well-known/agents.json",
            version="1.0.0",
            warning="This is a non-standard extension to A2A protocol"
        )
        
    except Exception as e:
        logger.error(f"Error in agent registry discovery: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Agent registry discovery failed")


@router.get("/a2a-info.json")
async def get_a2a_info(request: Request) -> dict:
    """A2A protocol information endpoint.
    
    Provides information about A2A protocol support and compliance details.
    """
    base_url = get_base_url(request)
    
    return {
        "protocol": "A2A",
        "version": "1.0.0",
        "server": "AgentArea",
        "compliance": {
            "a2a_specification": "https://a2aproject.github.io/A2A/latest/specification/",
            "rfc_8615": "https://tools.ietf.org/html/rfc8615",
            "json_rpc": "https://www.jsonrpc.org/specification/v2"
        },
        "discovery": {
            "standard": {
                "agent_card": f"{base_url}/.well-known/agent.json",
                "description": "Standard A2A discovery - returns agent for this domain/subdomain"
            },
            "agent_specific": {
                "endpoint": f"{base_url}/v1/agents/{{agent_id}}/card",
                "description": "Direct agent card access via agent ID"
            },
            "non_standard": {
                "agent_registry": f"{base_url}/.well-known/agents.json",
                "warning": "Non-standard extension for multi-agent environments"
            }
        },
        "recommended_deployment": {
            "single_agent": "Use domain.com/.well-known/agent.json",
            "multi_agent": "Use subdomains: agent1.domain.com, agent2.domain.com",
            "enterprise": "Deploy external agent registry/catalog service"
        },
        "communication_endpoints": {
            "rpc": f"{base_url}/v1/agents/{{agent_id}}/rpc",
            "stream": f"{base_url}/v1/agents/{{agent_id}}/stream",
            "tasks": f"{base_url}/v1/agents/{{agent_id}}/tasks/"
        },
        "supported_methods": [
            "tasks/send",  # A2A standard method
            "message/send",  # Legacy compatibility
            "message/stream", 
            "tasks/get",
            "tasks/cancel",
            "agent/authenticatedExtendedCard"
        ],
        "capabilities": {
            "streaming": True,
            "pushNotifications": False,
            "stateTransitionHistory": True
        },
        "authentication": {
            "supported": True,
            "methods": ["bearer", "api_key"],
            "required": False
        }
    }


@router.get("/")
async def well_known_index(request: Request) -> dict:
    """Index of available well-known endpoints."""
    base_url = get_base_url(request)
    
    return {
        "message": "AgentArea A2A Protocol Well-Known Endpoints",
        "endpoints": {
            "agent.json": f"{base_url}/.well-known/agent.json",
            "agents.json": f"{base_url}/.well-known/agents.json", 
            "a2a-info.json": f"{base_url}/.well-known/a2a-info.json"
        },
        "specification": "https://a2aproject.github.io/A2A/latest/specification/",
        "rfc": "https://tools.ietf.org/html/rfc8615"
    }