"""A URL MCP connection's secret headers reach its upstream on every path.

Creating a connection moves its credential headers out of ``json_spec`` into
the secret store. Verification and tool calls rebuilt the outbound headers from
``json_spec`` alone, so the upstream never received the credential and the
connection failed with 401.
"""

from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import httpx2
import pytest
from agentarea_common.testing import install_graph_ownership_stub
from agentarea_common.testing.mocks import TestSecretManager as InMemorySecrets
from agentarea_mcp.application import mcp_client
from agentarea_mcp.application.service import MCPServerInstanceService
from agentarea_mcp.domain.mpc_server_instance_model import MCPServerInstance
from agentarea_mcp.schemas.dto import MCPServerInstanceCreate

ENDPOINT = "https://mcp.example.com/mcp"
CREDENTIAL = "sk-live-canary"
SPEC_ID = "00000000-0000-4000-8000-0000000000aa"


@pytest.fixture(autouse=True)
def graph(monkeypatch):
    return install_graph_ownership_stub(monkeypatch)


class _Upstream:
    """The member's MCP server: records each request and refuses it."""

    def __init__(self) -> None:
        self.requests: list[httpx2.Request] = []

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        return httpx2.Response(401)

    def client_factory(self, headers=None, timeout=None, auth=None, inner=None):
        return httpx2.AsyncClient(
            headers=headers,
            timeout=timeout,
            auth=auth,
            transport=httpx2.MockTransport(self._handle),
        )

    def received(self, header: str) -> set[str | None]:
        return {request.headers.get(header) for request in self.requests}


class _Session:
    """Answers verify()'s reads: the locked instance, then its server spec."""

    def __init__(self, rows) -> None:
        self._rows = list(rows)

    @asynccontextmanager
    async def begin(self):
        yield

    async def execute(self, _stmt):
        result = MagicMock()
        result.scalar_one_or_none.return_value = self._rows.pop(0) if self._rows else None
        return result

    async def flush(self):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False


def _server() -> MagicMock:
    server = MagicMock()
    server.id = SPEC_ID
    server.remote_url = ENDPOINT
    server.cmd = None
    server.docker_image_url = None
    server.json_spec = {"type": "url", "endpoint_url": ENDPOINT}
    server.env_schema = []
    return server


def _service(server: MagicMock) -> MCPServerInstanceService:
    with patch("agentarea_mcp.application.service.get_database", MagicMock()):
        service = MCPServerInstanceService(
            repository_factory=MagicMock(),
            event_broker=MagicMock(publish=AsyncMock()),
            secret_manager=InMemorySecrets(),
        )
    service.era_verdict_store = None
    service.mcp_server_repository = MagicMock()
    service.mcp_server_repository.get_server_by_id = AsyncMock(return_value=server)
    repository = MagicMock()
    repository.user_context = MagicMock(user_id="user", workspace_id="ws")
    server.workspace_id = "ws"
    repository.session = MagicMock(
        commit=AsyncMock(), refresh=AsyncMock(), rollback=AsyncMock(), flush=AsyncMock()
    )
    service.repository = repository
    return service


async def _connect(service: MCPServerInstanceService, upstream: _Upstream) -> MCPServerInstance:
    """Create the connection as the webapp does: every header is a secret."""
    server = await service.mcp_server_repository.get_server_by_id(SPEC_ID)
    created: list[MCPServerInstance] = []
    service.repository.session.add = lambda instance: (
        setattr(instance, "id", uuid.uuid4()),
        created.append(instance),
    )
    db = MagicMock(async_session_factory=lambda: _Session([created[0], server]))
    with (
        patch("agentarea_mcp.verification.get_database", return_value=db),
        patch("agentarea_mcp.verification._save_verification", new=AsyncMock()),
        patch.object(mcp_client, "shared_era_verdict_store", return_value=None),
        patch.object(mcp_client, "pinned_client_factory", return_value=upstream.client_factory),
        patch(
            "agentarea_mcp.application.service.MCPConfigurationValidator.validate_json_spec",
            return_value=[],
        ),
    ):
        instance = await service.create_instance(
            MCPServerInstanceCreate(
                name="remote",
                server_spec_id=uuid.UUID(SPEC_ID),
                json_spec={"type": "url", "headers": {"X-Api-Key": CREDENTIAL}},
            )
        )
    assert instance is not None
    service.repository.get_by_id = AsyncMock(return_value=instance)
    return instance


@pytest.mark.asyncio
async def test_the_credential_is_stored_out_of_the_spec_and_sent_on_the_create_probe():
    service = _service(_server())
    upstream = _Upstream()

    instance = await _connect(service, upstream)

    assert CREDENTIAL not in json.dumps(instance.json_spec)
    assert upstream.requests
    assert upstream.received("x-api-key") == {CREDENTIAL}


@pytest.mark.asyncio
async def test_a_tool_call_sends_the_stored_credential_upstream():
    service = _service(_server())
    instance = await _connect(service, _Upstream())
    upstream = _Upstream()

    with patch("agentarea_execution.activities.agent_execution_activities._enqueue_last_dispatch"):
        result = await service.execute_tool(
            instance.id, "search", {}, httpx_client_factory=upstream.client_factory
        )

    assert result["success"] is False
    assert upstream.requests
    assert upstream.received("x-api-key") == {CREDENTIAL}


@pytest.mark.asyncio
async def test_reverify_sends_the_stored_credential_upstream():
    server = _server()
    service = _service(server)
    instance = await _connect(service, _Upstream())
    upstream = _Upstream()

    db = MagicMock(async_session_factory=lambda: _Session([instance, server]))
    with (
        patch("agentarea_mcp.verification.get_database", return_value=db),
        patch("agentarea_mcp.verification._save_verification", new=AsyncMock()),
        patch.object(mcp_client, "shared_era_verdict_store", return_value=None),
        patch.object(mcp_client, "pinned_client_factory", return_value=upstream.client_factory),
    ):
        await service.verify_instance(instance.id)

    assert upstream.requests
    assert upstream.received("x-api-key") == {CREDENTIAL}


@pytest.mark.asyncio
async def test_the_proxy_headers_include_the_stored_credential():
    service = _service(_server())
    instance = await _connect(service, _Upstream())

    assert await service.outbound_headers(instance) == {"X-Api-Key": CREDENTIAL}


@pytest.mark.asyncio
async def test_a_container_connection_never_sends_its_environment_as_headers():
    server = _server()
    server.remote_url = None
    server.docker_image_url = "ghcr.io/acme/server:1"
    server.json_spec = {"type": "docker", "image": "ghcr.io/acme/server:1"}
    service = _service(server)
    instance = MCPServerInstance(
        name="local", server_spec_id=SPEC_ID, transport="docker", json_spec={"env_vars": ["TOKEN"]}
    )
    instance.id = uuid.uuid4()
    await service.env_service.set_instance_environment(instance.id, {"TOKEN": CREDENTIAL})

    assert await service.outbound_headers(instance) == {}
