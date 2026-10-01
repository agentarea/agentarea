"""Read the card of an A2A agent by its address, before it is added as a delegate.

The agent form asks only for an address: the card says who the agent is, so
its name and description fill the form, and a wrong address is caught before
the delegate is saved rather than on its first call.
"""

from a2a.client import A2ACardResolver, AgentCardResolutionError
from agentarea_agents_sdk.tools.a2a_agent_tool import agent_address
from agentarea_common.auth.dependencies import UserContextDep
from agentarea_common.auth.route_authz import unrestricted
from agentarea_common.utils.url_safety import safe_async_client
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/a2a", tags=["a2a"])

_CARD_TIMEOUT = 10.0


class AgentCardLookup(BaseModel):
    url: str = Field(description="The agent's address, or the URL of its agent card")


class AgentCardSkill(BaseModel):
    name: str
    description: str


class AgentCardSummary(BaseModel):
    address: str = Field(description="The agent's address, the form a delegate stores")
    name: str
    description: str
    skills: list[AgentCardSkill]


@router.post(
    "/agent-cards",
    response_model=AgentCardSummary,
    dependencies=[
        unrestricted(
            "reads a public discovery document through the outbound guard; "
            "membership is checked by the workspace path"
        )
    ],
)
async def read_agent_card(data: AgentCardLookup, _user: UserContextDep) -> AgentCardSummary:
    """The card published at an A2A agent's address."""
    address = agent_address(data.url)
    async with safe_async_client(timeout=_CARD_TIMEOUT) as client:
        try:
            card = await A2ACardResolver(client, address).get_agent_card()
        except AgentCardResolutionError as e:
            raise HTTPException(status_code=400, detail=f"No agent card at {address}: {e}") from e
    return AgentCardSummary(
        address=address,
        name=card.name,
        description=card.description,
        skills=[AgentCardSkill(name=s.name, description=s.description) for s in card.skills],
    )
