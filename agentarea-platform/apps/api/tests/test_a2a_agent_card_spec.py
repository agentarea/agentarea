from types import SimpleNamespace
from uuid import uuid4

from a2a.types import AgentCard
from agentarea_api.api.v1.a2a_card import agent_card_json, build_agent_card
from google.protobuf.json_format import ParseDict


def _agent():
    return SimpleNamespace(
        name="spec-agent",
        description="A spec-visible agent",
        tools=[{"name": "web_search"}],
        planning=True,
        a2ui_enabled=False,
    )


def test_agent_card_json_parses_strictly_as_a_v1_card():
    agent_id = uuid4()
    card = build_agent_card(
        _agent(), base_url="https://api.example.com", agent_id=agent_id, extended=False
    )
    payload = agent_card_json(card)

    # No compat shim: unknown or 0.3-shaped fields would fail this parse.
    ParseDict(payload, AgentCard())

    assert payload["supportedInterfaces"] == [
        {
            "url": f"https://api.example.com/v1/agents/{agent_id}/a2a/rpc",
            "protocolBinding": "JSONRPC",
            "protocolVersion": "1.0",
        }
    ]
    assert payload["securitySchemes"] == {
        "bearer": {"httpAuthSecurityScheme": {"scheme": "bearer"}}
    }
    assert payload["securityRequirements"] == [{"schemes": {"bearer": {}}}]
    assert "security" not in payload
    assert payload["capabilities"] == {
        "streaming": True,
        "pushNotifications": True,
        "extendedAgentCard": True,
    }
    assert payload["provider"]["url"] == "https://api.example.com"
    assert all(skill.get("tags") for skill in payload["skills"])


def test_public_card_lists_only_the_generic_skill():
    card = build_agent_card(_agent(), base_url="https://a", agent_id=uuid4(), extended=False)

    assert [skill.id for skill in card.skills] == ["text-processing"]


def test_extended_card_adds_tool_and_planning_skills():
    card = build_agent_card(_agent(), base_url="https://a", agent_id=uuid4(), extended=True)

    assert [skill.id for skill in card.skills] == [
        "text-processing",
        "tool-execution",
        "task-planning",
    ]


def test_a2ui_agent_advertises_the_extension():
    card = build_agent_card(
        SimpleNamespace(name="ui", description=None, tools=None, planning=None, a2ui_enabled=True),
        base_url="https://a",
        agent_id=uuid4(),
        extended=False,
    )
    payload = agent_card_json(card)

    ParseDict(payload, AgentCard())
    [extension] = payload["capabilities"]["extensions"]
    assert extension["uri"] == "https://a2ui.org/a2a-extension/a2ui/v0.9"
    assert extension["params"]["supportedCatalogIds"] == [
        "https://a2ui.org/specification/v0_9/basic_catalog.json"
    ]
    assert payload["description"] == "AI agent ui"
