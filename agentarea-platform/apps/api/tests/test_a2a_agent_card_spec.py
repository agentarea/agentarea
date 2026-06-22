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

    rpc_url = f"https://api.example.com/v1/agents/{agent_id}/a2a/rpc"
    # A2A v1.0.0 transport advertising: supportedInterfaces[] (first = preferred).
    assert "url" not in payload
    assert "protocolVersion" not in payload
    assert "preferredTransport" not in payload
    assert "additionalInterfaces" not in payload
    assert payload["supportedInterfaces"] == [
        {"url": rpc_url, "protocolBinding": "JSONRPC", "protocolVersion": "1.0"}
    ]
    # extended-card flag moved into capabilities
    assert payload["capabilities"]["extendedAgentCard"] is True
    assert "stateTransitionHistory" not in payload["capabilities"]
    # provider.url is required by spec
    assert payload["provider"]["url"] == "https://api.example.com"
    # every skill must carry tags (required by spec)
    assert all(skill.get("tags") for skill in payload["skills"])
    assert payload["securitySchemes"]["bearer"]["type"] == "http"
    assert payload["security"] == [{"bearer": []}]
