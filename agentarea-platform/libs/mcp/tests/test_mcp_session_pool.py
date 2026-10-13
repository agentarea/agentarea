"""Tool calls reuse a connected MCP client instead of negotiating on every call.

The server is a real MCP server behind the SDK's streamable HTTP app, wrapped to
record every request it receives. Before pooling, three calls were three
connections and three negotiations; now they are one.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx2
import pytest
from agentarea_common.testing.mocks import TestSecretManager as InMemorySecrets
from agentarea_mcp.application import mcp_session_pool
from agentarea_mcp.application import service as service_module
from agentarea_mcp.application.mcp_session_pool import MCPSessionPool
from agentarea_mcp.application.service import MCPServerInstanceService
from agentarea_mcp.domain.mpc_server_instance_model import MCPServerInstance
from agentarea_mcp.tool_context import (
    CONTEXT_HEADER,
    CONTEXT_SECRET_NAME,
    CONTEXT_SIGNING_FLAG,
    ToolCallContext,
)
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

ENDPOINT = "http://127.0.0.1/"
SPEC_ID = "00000000-0000-4000-8000-0000000000dd"
SECRET = "s" * 40  # pragma: allowlist secret
NEGOTIATIONS = {"initialize", "server/discover"}


class _App:
    """A real MCP server that records the JSON-RPC method and headers of each request.

    ``legacy`` refuses ``server/discover`` the way a 2025 server does, so the
    client falls back to ``initialize`` and the server issues a session id.
    """

    def __init__(self, *, legacy: bool = False) -> None:
        self.requests: list[dict[str, Any]] = []
        self.forget_session_once = False
        self.legacy = legacy
        server = MCPServer(name="pool")

        def echo(text: str) -> str:
            return text

        server.add_tool(echo, name="echo")
        self._asgi = server.streamable_http_app(
            streamable_http_path="/",
            stateless_http=not legacy,
            json_response=legacy,
            transport_security=TransportSecuritySettings(
                allowed_hosts=["127.0.0.1"], allowed_origins=["http://127.0.0.1"]
            ),
        )
        self.factory_calls = 0

    async def asgi(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST":
            await self._asgi(scope, receive, send)
            return
        body = b""
        more = True
        while more:
            message = await receive()
            body += message.get("body", b"")
            more = message.get("more_body", False)
        payload = json.loads(body) if body else {}
        headers = {key.decode().lower(): value.decode() for key, value in scope["headers"]}
        method = payload.get("method")
        self.requests.append({"method": method, "headers": headers})

        replayed = False

        async def replay():
            nonlocal replayed
            if replayed:
                return await receive()
            replayed = True
            return {"type": "http.request", "body": body, "more_body": False}

        refuse = (self.legacy and method == "server/discover") or (
            self.forget_session_once and method == "tools/call" and "mcp-session-id" in headers
        )
        if refuse:
            if method == "tools/call":
                self.forget_session_once = False
            await send({"type": "http.response.start", "status": 404, "headers": []})
            await send({"type": "http.response.body", "body": b""})
            return
        await self._asgi(scope, replay, send)

    def factory(self, _wrapped=None):
        def build(headers=None, timeout=None, auth=None, **_kwargs):
            self.factory_calls += 1
            return httpx2.AsyncClient(
                headers=headers,
                timeout=timeout,
                auth=auth,
                transport=httpx2.ASGITransport(app=self.asgi),
            )

        return build

    def methods(self) -> list[str]:
        return [request["method"] for request in self.requests]

    def negotiations(self) -> int:
        return sum(1 for method in self.methods() if method in NEGOTIATIONS)


def _server() -> MagicMock:
    server = MagicMock()
    server.id = SPEC_ID
    server.workspace_id = "ws-1"
    server.remote_url = ENDPOINT
    server.cmd = None
    server.docker_image_url = None
    server.json_spec = {
        "type": "url",
        "endpoint_url": ENDPOINT,
        "remotes": [{"type": "streamable-http", "url": ENDPOINT}],
    }
    server.env_schema = []
    return server


def _instance(json_spec: dict[str, Any] | None = None) -> MCPServerInstance:
    instance = MCPServerInstance(
        name="pool",
        server_spec_id=SPEC_ID,
        transport="url",
        json_spec={"type": "url", **(json_spec or {})},
    )
    instance.id = uuid.uuid4()
    instance.auth_config_id = None
    return instance


def _service(instance: MCPServerInstance) -> MCPServerInstanceService:
    with patch("agentarea_mcp.application.service.get_database", MagicMock()):
        service = MCPServerInstanceService(
            repository_factory=MagicMock(),
            event_broker=MagicMock(publish=AsyncMock()),
            secret_manager=InMemorySecrets(),
        )
    service.era_verdict_store = None
    service.mcp_server_repository = MagicMock()
    service.mcp_server_repository.get_server_by_id = AsyncMock(return_value=_server())
    repository = MagicMock()
    repository.user_context = MagicMock(user_id="user", workspace_id="ws-1")
    repository.get_by_id = AsyncMock(return_value=instance)
    service.repository = repository
    return service


def _context(call: str) -> ToolCallContext:
    return ToolCallContext(
        task_id="task-1", tool_call_id=call, workspace_id="ws-1", agent_id="agent-1"
    )


@pytest.fixture
async def pool(monkeypatch):
    pool = MCPSessionPool()
    monkeypatch.setattr(service_module, "session_pool", lambda: pool)
    yield pool
    await pool.aclose()


async def _calls(service, instance, app, pool, n: int, **kwargs) -> list[dict[str, Any]]:
    results = []
    with (
        patch.object(service_module, "pinned_client_factory", app.factory),
        patch.object(service_module, "record_dispatch"),
    ):
        async with app._asgi.router.lifespan_context(app._asgi):
            for i in range(n):
                results.append(
                    await service.execute_tool(
                        instance.id,
                        "echo",
                        {"text": f"call {i}"},
                        call_context=_context(f"call-{i}"),
                        **kwargs,
                    )
                )
            await pool.aclose()
    return results


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy", [False, True], ids=["modern", "legacy-session"])
async def test_three_calls_negotiate_once(pool, legacy):
    instance = _instance()
    service = _service(instance)
    app = _App(legacy=legacy)

    results = await _calls(service, instance, app, pool, 3)

    assert [r["result"] for r in results] == ["call 0", "call 1", "call 2"]
    assert app.methods().count("tools/call") == 3
    # A 2025 server is probed once with server/discover, then initialized once.
    assert app.negotiations() == (2 if legacy else 1)
    assert app.methods().count("initialize") == (1 if legacy else 0)
    assert app.factory_calls == 1


@pytest.mark.asyncio
async def test_a_paying_client_factory_never_shares_a_connection(pool):
    instance = _instance()
    service = _service(instance)
    app = _App()

    def paying_factory(headers=None, timeout=None, auth=None, inner=None):
        raise AssertionError("replaced by the patched pinned factory")

    await _calls(service, instance, app, pool, 3, httpx_client_factory=paying_factory)

    assert app.negotiations() == 3
    assert pool.idle_count == 0


@pytest.mark.asyncio
async def test_signed_context_rides_only_on_its_own_call(pool):
    instance = _instance({CONTEXT_SIGNING_FLAG: True})
    service = _service(instance)
    await service.env_service.set_instance_environment(instance.id, {CONTEXT_SECRET_NAME: SECRET})
    app = _App()

    await _calls(service, instance, app, pool, 3)

    assert app.negotiations() == 1
    header = CONTEXT_HEADER.lower()
    tokens = [r["headers"].get(header) for r in app.requests if r["method"] == "tools/call"]
    assert len(tokens) == 3 and all(tokens) and len(set(tokens)) == 3
    # The connection is not the call's: negotiating it carried no call's context.
    assert all(header not in r["headers"] for r in app.requests if r["method"] in NEGOTIATIONS)


@pytest.mark.asyncio
async def test_different_credentials_never_share_a_connection(pool):
    instance = _instance()
    service = _service(instance)
    app = _App()
    tokens = iter(["Bearer alice", "Bearer bob", "Bearer alice"])

    async def outbound_headers(_instance, _spec):
        return {"Authorization": next(tokens)}

    service._outbound_headers = outbound_headers
    await _calls(service, instance, app, pool, 3)

    calls = [r["headers"]["authorization"] for r in app.requests if r["method"] == "tools/call"]
    assert calls == ["Bearer alice", "Bearer bob", "Bearer alice"]
    negotiated_as = [
        r["headers"]["authorization"] for r in app.requests if r["method"] in NEGOTIATIONS
    ]
    assert negotiated_as == ["Bearer alice", "Bearer bob"]


@pytest.mark.asyncio
async def test_a_session_the_server_forgot_is_reopened_and_the_call_sent_again(pool):
    instance = _instance()
    service = _service(instance)
    app = _App(legacy=True)

    with (
        patch.object(service_module, "pinned_client_factory", app.factory),
        patch.object(service_module, "record_dispatch"),
    ):
        async with app._asgi.router.lifespan_context(app._asgi):
            first = await service.execute_tool(instance.id, "echo", {"text": "one"})
            app.forget_session_once = True
            second = await service.execute_tool(instance.id, "echo", {"text": "two"})
            await pool.aclose()

    assert first["result"] == "one"
    assert second["success"] is True and second["result"] == "two"
    assert app.methods().count("initialize") == 2


@pytest.mark.asyncio
async def test_a_failed_call_does_not_return_its_connection(pool):
    instance = _instance()
    service = _service(instance)
    app = _App()

    with (
        patch.object(service_module, "pinned_client_factory", app.factory),
        patch.object(service_module, "record_dispatch"),
    ):
        async with app._asgi.router.lifespan_context(app._asgi):
            result = await service.execute_tool(instance.id, "missing", {})
            assert pool.idle_count in (0, 1)
            await pool.aclose()

    assert result["success"] is False


class _FakeConnected:
    closed = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        _FakeConnected.closed += 1


@pytest.mark.asyncio
async def test_idle_connections_expire_and_the_pool_is_bounded():
    _FakeConnected.closed = 0
    pool = MCPSessionPool(idle_seconds=0.05, max_idle_per_key=2, max_idle=3)
    keys = [
        mcp_session_pool.session_key(
            f"http://s{i}/",
            {},
            transport=None,
            egress="pinned",
            verdict_key=None,
            timeout_seconds=300,
        )
        for i in range(3)
    ]

    async def hold(key, release: asyncio.Event):
        async with pool.lease(key, _FakeConnected):
            await release.wait()

    release = asyncio.Event()
    holders = [asyncio.create_task(hold(keys[0], release)) for _ in range(3)]
    holders += [asyncio.create_task(hold(key, release)) for key in keys[1:]]
    await asyncio.sleep(0.01)
    release.set()
    await asyncio.gather(*holders)
    await asyncio.sleep(0.01)

    # Three for keys[0] but only two may idle there; five in all but only three may idle.
    assert pool.idle_count == 3
    assert _FakeConnected.closed == 2

    await asyncio.sleep(0.1)
    assert pool.idle_count == 0
    assert _FakeConnected.closed == 5
    await pool.aclose()
