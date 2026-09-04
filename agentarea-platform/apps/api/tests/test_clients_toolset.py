"""Unit tests for the clients (harness) toolset.

A registered client is what a codex/claude harness connects as, so the tools
have to hand back the endpoint URL and keep the ReBAC ownership grant that the
REST router writes — a client nobody owns is invisible to authorization.
"""

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from agentarea_api.tools import clients_toolset
from agentarea_api.tools.clients_toolset import ClientsToolset
from pydantic import ValidationError

CLIENT_ID = uuid4()


class FakeClientService:
    def __init__(self):
        self.created: list = []
        self.updated: list = []
        self.associations: list = []
        self.deleted: list = []

    async def create_client(self, payload):
        self.created.append(payload)
        return SimpleNamespace(id=CLIENT_ID, name=payload.name, kind=payload.kind)

    async def update_client(self, client_id, payload):
        self.updated.append((client_id, payload))
        return SimpleNamespace(id=client_id, name=payload.name or "unchanged", kind="harness")

    async def get(self, client_id):
        return SimpleNamespace(
            id=client_id,
            name="codex",
            description=None,
            kind="harness",
            skills=[SimpleNamespace(id=uuid4(), name="research")],
            mcp_instances=[],
        )

    async def list(self, limit=None, offset=None):
        return [SimpleNamespace(id=CLIENT_ID, name="codex", kind="harness")]

    async def delete(self, client_id):
        self.deleted.append(client_id)
        return True

    async def add_skill(self, client_id, skill_id):
        self.associations.append(("add_skill", client_id, skill_id))

    async def remove_skill(self, client_id, skill_id):
        self.associations.append(("remove_skill", client_id, skill_id))

    async def add_mcp_instance(self, client_id, mcp_instance_id, namespace_prefix=None):
        self.associations.append(("add_mcp", client_id, mcp_instance_id, namespace_prefix))

    async def remove_mcp_instance(self, client_id, mcp_instance_id):
        self.associations.append(("remove_mcp", client_id, mcp_instance_id))


@pytest.fixture
def service(monkeypatch) -> FakeClientService:
    fake = FakeClientService()
    grants: list = []

    @asynccontextmanager
    async def fake_context():
        user_ctx = SimpleNamespace(user_id="user-1", workspace_id="ws-1")
        yield None, user_ctx, SimpleNamespace(), None, None

    async def fake_grant(*, resource_id, workspace_id, user_id):
        grants.append((str(resource_id), workspace_id, user_id))

    monkeypatch.setattr(clients_toolset, "platform_context", fake_context)
    monkeypatch.setattr(clients_toolset, "platform_read_context", fake_context)
    monkeypatch.setattr(clients_toolset, "grant_resource_owner", fake_grant)
    monkeypatch.setattr(clients_toolset, "_build_service", lambda _repo_factory: fake)
    fake.grants = grants
    return fake


async def test_create_returns_endpoint_url_and_grants_ownership(service):
    result = json.loads(await ClientsToolset().create(name="codex"))

    assert result["id"] == str(CLIENT_ID)
    assert result["mcp_endpoint_url"].endswith(f"/client-mcp/{CLIENT_ID}")
    assert service.created[0].name == "codex"
    assert service.created[0].kind == "harness"
    assert service.grants == [(str(CLIENT_ID), "ws-1", "user-1")]


async def test_create_rejects_unknown_kind_loudly(service):
    with pytest.raises(ValidationError, match="kind"):
        await ClientsToolset().create(name="codex", kind="x" * 64)


async def test_update_only_sends_provided_fields(service):
    await ClientsToolset().update(client_id=str(CLIENT_ID), description="my laptop")

    _client_id, payload = service.updated[0]
    assert payload.model_dump(exclude_unset=True) == {"description": "my laptop"}


async def test_add_mcp_instance_passes_namespace_prefix(service):
    instance_id = uuid4()
    await ClientsToolset().add_mcp_instance(
        client_id=str(CLIENT_ID),
        mcp_instance_id=str(instance_id),
        namespace_prefix="gh",
    )

    assert service.associations == [("add_mcp", CLIENT_ID, instance_id, "gh")]


async def test_get_lists_attached_skills(service):
    result = json.loads(await ClientsToolset().get(client_id=str(CLIENT_ID)))

    assert result["skills"][0]["name"] == "research"
    assert result["mcp_endpoint_url"].endswith(f"/client-mcp/{CLIENT_ID}")
