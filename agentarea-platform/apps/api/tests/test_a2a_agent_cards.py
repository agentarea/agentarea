"""The agent form reads a remote agent's card from the address it is given."""

import httpx
from a2a.types import AgentCard, AgentInterface, AgentSkill
from agentarea_api.api.v1 import a2a_agent_cards
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.dependencies import get_user_context
from fastapi import FastAPI
from fastapi.testclient import TestClient
from google.protobuf.json_format import MessageToDict

ADDRESS = "https://4f1c.a2a.agentarea.example"
CARD = AgentCard(
    name="docs-writer",
    description="Writes documentation.",
    supported_interfaces=[
        AgentInterface(url=f"{ADDRESS}/", protocol_binding="JSONRPC", protocol_version="1.0")
    ],
    skills=[AgentSkill(id="docs", name="Docs", description="Writes docs", tags=["docs"])],
)


def _client(monkeypatch, handle) -> tuple[TestClient, list[str]]:
    fetched: list[str] = []

    def record(request: httpx.Request) -> httpx.Response:
        fetched.append(str(request.url))
        return handle(request)

    monkeypatch.setattr(
        a2a_agent_cards,
        "safe_async_client",
        lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(record), **kwargs),
    )
    app = FastAPI()
    app.include_router(a2a_agent_cards.router, prefix="/v1/workspaces/{workspace}")
    app.dependency_overrides[get_user_context] = lambda: UserContext(
        user_id="u", workspace_id="ws"
    )
    return TestClient(app), fetched


def test_the_card_at_an_address_names_the_agent(monkeypatch):
    client, fetched = _client(monkeypatch, lambda r: httpx.Response(200, json=MessageToDict(CARD)))

    response = client.post(
        "/v1/workspaces/acme/a2a/agent-cards",
        json={"url": f" {ADDRESS}/.well-known/agent-card.json "},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "address": ADDRESS,
        "name": "docs-writer",
        "description": "Writes documentation.",
        "skills": [{"name": "Docs", "description": "Writes docs"}],
    }
    assert fetched == [f"{ADDRESS}/.well-known/agent-card.json"]


def test_an_address_without_a_card_is_refused_naming_it(monkeypatch):
    client, _ = _client(monkeypatch, lambda r: httpx.Response(404))

    response = client.post("/v1/workspaces/acme/a2a/agent-cards", json={"url": ADDRESS})

    assert response.status_code == 400
    assert ADDRESS in response.json()["detail"]
