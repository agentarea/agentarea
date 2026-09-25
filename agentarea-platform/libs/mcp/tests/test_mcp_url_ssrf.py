"""URL-type MCP instances dial member-supplied URLs only through the pinned transport.

verify(), execute_tool and validate_connection connected through the MCP SDK's
own httpx2 client, which resolves the name itself: a member's URL reached
internal hosts, and the raw connection error came back as the verification
message, a port and status oracle.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import httpx2
import pytest
from agentarea_common.utils.url_safety import OutboundPolicy, UnsafeUrlError
from agentarea_mcp.application import mcp_client
from agentarea_mcp.application.mcp_client import SafeMCPTransport, pinned_client_factory
from agentarea_mcp.application.service import MCPServerInstanceService
from agentarea_mcp.application.validation_service import MCPValidationError
from agentarea_mcp.domain.verification_types import DEFAULT_VERIFICATION


class _Session:
    """Answers verify()'s two reads: the locked instance, then its server spec."""

    def __init__(self, instance, server) -> None:
        self._rows = [instance, server]

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


def _url_instance_db(endpoint_url: str):
    instance = MagicMock(
        id=uuid.uuid4(),
        json_spec={},
        verification=dict(DEFAULT_VERIFICATION),
        last_dispatch=None,
        tools=None,
        server_spec_id="spec",
    )
    server = MagicMock(remote_url=endpoint_url, json_spec={}, cmd=None, docker_image_url=None)
    session = _Session(instance, server)
    return instance, MagicMock(async_session_factory=lambda: session)


def _resolver(table: dict[str, list[str]]):
    async def resolve(host: str, port: int) -> list[str]:
        return table[host]

    return resolve


@pytest.fixture(autouse=True)
def _closed_policy(monkeypatch):
    from agentarea_common.config import get_settings

    monkeypatch.delenv("ALLOW_PRIVATE_URLS", raising=False)
    monkeypatch.delenv("OUTBOUND_PRIVATE_ALLOWLIST", raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_the_mcp_client_never_dials_a_name_that_resolves_private():
    dialed: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        dialed.append(request)
        return httpx2.Response(200)

    factory = pinned_client_factory(
        policy=OutboundPolicy(),
        resolve=_resolver({"mcp.internal.example": ["10.0.0.5"]}),
        inner=lambda: httpx2.MockTransport(handler),
    )

    with pytest.raises(BaseException) as raised:  # noqa: PT011
        async with mcp_client.connected_mcp_client(
            "http://mcp.internal.example/mcp",
            None,
            2.0,
            transport="streamable-http",
            httpx_client_factory=factory,
        ):
            pass

    assert dialed == []
    leaves = raised.value.exceptions if isinstance(raised.value, BaseExceptionGroup) else [raised.value]
    assert any(isinstance(leaf, UnsafeUrlError) for leaf in leaves)


@pytest.mark.asyncio
async def test_a_public_mcp_host_is_dialed_at_its_vetted_address():
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200)

    factory = pinned_client_factory(
        policy=OutboundPolicy(),
        resolve=_resolver({"mcp.example.com": ["93.184.216.34"]}),
        inner=lambda: httpx2.MockTransport(handler),
    )
    async with factory(headers=None, timeout=None) as client:
        await client.post("https://mcp.example.com/mcp", json={})

    (pinned,) = seen
    assert pinned.url.host == "93.184.216.34"
    assert pinned.headers["host"] == "mcp.example.com"
    assert pinned.extensions["sni_hostname"] == "mcp.example.com"


@pytest.mark.asyncio
async def test_verify_refuses_a_private_endpoint_and_reports_it_generically():
    inst, db_mock = _url_instance_db("http://10.0.0.5:6379/mcp")

    with (
        patch("agentarea_mcp.verification.get_database", return_value=db_mock),
        patch("agentarea_mcp.verification._save_verification", new=AsyncMock()),
        patch.object(mcp_client, "shared_era_verdict_store", return_value=None),
    ):
        from agentarea_mcp.verification import verify

        result = await verify(inst)

    assert result["status"] == "failed"
    message = result["error"]["message"]
    assert "10.0.0.5" not in message
    assert "6379" not in message
    assert message == "Could not connect to the MCP server"


def _service() -> MCPServerInstanceService:
    with patch("agentarea_mcp.application.service.get_database", MagicMock()):
        return MCPServerInstanceService(
            repository_factory=MagicMock(),
            event_broker=MagicMock(),
            secret_manager=MagicMock(),
        )


def _capture_factory():
    captured: dict[str, object] = {}

    @asynccontextmanager
    async def fake_connected(url, headers, timeout, **kwargs):
        captured["url"] = url
        captured["factory"] = kwargs.get("httpx_client_factory")
        client = MagicMock()
        client.call_tool = AsyncMock(return_value=MagicMock(content=[], is_error=False))
        client.list_tools = AsyncMock(return_value=MagicMock(tools=[]))
        yield client

    return captured, fake_connected


@pytest.mark.asyncio
async def test_execute_tool_dials_a_url_instance_through_the_pinned_transport():
    service = _service()
    instance = MagicMock(id=uuid.uuid4(), auth_config_id=None, json_spec={"type": "url"})
    instance.name = "remote"
    service.repository = MagicMock()
    service.repository.get_by_id = AsyncMock(return_value=instance)
    spec = {"type": "url", "endpoint_url": "https://mcp.example.com/mcp"}
    captured, fake_connected = _capture_factory()

    with (
        patch.object(service, "_get_transport_spec_for_instance", new=AsyncMock(return_value=spec)),
        patch("agentarea_mcp.application.service.connected_mcp_client", fake_connected),
        patch("agentarea_execution.activities.agent_execution_activities._enqueue_last_dispatch"),
    ):
        result = await service.execute_tool(instance.id, "search", {})

    assert result["success"] is True
    factory = captured["factory"]
    assert callable(factory)
    client = factory(headers=None, timeout=None)
    assert isinstance(client._transport, SafeMCPTransport)


@pytest.mark.asyncio
async def test_validate_connection_dials_through_the_pinned_transport():
    service = _service()
    captured, fake_connected = _capture_factory()

    with patch("agentarea_mcp.application.service.connected_mcp_client", fake_connected):
        result = await service.validate_connection(url="https://8.8.8.8/mcp", headers={"a": "b"})

    assert result["valid"] is True
    client = captured["factory"](headers=None, timeout=None)  # type: ignore[operator]
    assert isinstance(client._transport, SafeMCPTransport)


@pytest.mark.asyncio
async def test_creating_a_url_instance_for_a_private_endpoint_is_refused():
    service = _service()
    service.repository = MagicMock()
    service.repository.session = MagicMock(rollback=AsyncMock(), commit=AsyncMock())
    server = MagicMock(
        id=uuid.uuid4(),
        workspace_id="ws",
        remote_url="http://169.254.169.254/latest/meta-data/",
        json_spec={},
        cmd=None,
        docker_image_url=None,
    )
    service.mcp_server_repository = MagicMock()
    service.mcp_server_repository.get_server_by_id = AsyncMock(return_value=server)
    service.repository.user_context = MagicMock(workspace_id="ws", user_id="u")

    from agentarea_mcp.schemas.dto import MCPServerInstanceCreate

    payload = MCPServerInstanceCreate(name="meta", server_spec_id=str(server.id), json_spec={})
    with pytest.raises(MCPValidationError):
        await service.create_instance(payload)
    service.repository.session.commit.assert_not_awaited()


def test_a_callers_own_factory_gets_a_pinned_inner_transport():
    from agentarea_common.utils.url_safety import SafeOutboundTransport

    received: dict[str, object] = {}

    def payment_factory(headers=None, timeout=None, auth=None, inner=None):
        received["inner"] = inner
        return MagicMock()

    pinned_client_factory(payment_factory, policy=OutboundPolicy())(headers=None, timeout=None)

    assert isinstance(received["inner"], SafeOutboundTransport)


@pytest.mark.asyncio
async def test_a_server_spec_pointing_at_the_metadata_address_is_refused():
    from agentarea_common.exceptions.errors import BadRequestError
    from agentarea_mcp.application.service import MCPServerService
    from agentarea_mcp.schemas.dto import MCPServerCreate

    service = MCPServerService(repository_factory=MagicMock())
    service.repository.resolve_unique_slug = AsyncMock(return_value="meta")
    payload = MCPServerCreate(
        name="meta", description="meta", remote_url="http://169.254.169.254/latest/"
    )

    with pytest.raises(BadRequestError):
        await service.create_mcp_server(payload)
