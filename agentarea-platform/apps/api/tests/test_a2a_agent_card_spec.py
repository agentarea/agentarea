from types import SimpleNamespace
from uuid import uuid4

import pytest
from agentarea_api.api.v1.agents_well_known import create_agent_card_for_agent


@pytest.mark.asyncio
async def test_agent_card_advertises_current_a2a_discovery_fields():
    agent_id = uuid4()
    agent = SimpleNamespace(
        name="spec-agent",
        description="A spec-visible agent",
        a2ui_enabled=False,
    )

    card = await create_agent_card_for_agent(agent, "https://api.example.com", agent_id)
    payload = card.model_dump(by_alias=True, exclude_none=True)

    assert payload["url"] == f"https://api.example.com/v1/agents/{agent_id}/a2a/rpc"
    assert payload["supportedInterfaces"] == [
        {
            "url": f"https://api.example.com/v1/agents/{agent_id}/a2a/rpc",
            "protocolBinding": "JSONRPC",
            "protocolVersion": "1.0",
        }
    ]
    assert payload["capabilities"]["extendedAgentCard"] is True
    assert payload["securitySchemes"]["bearer"]["type"] == "http"
    assert payload["security"] == [{"bearer": []}]
