"""Unit tests for the per-instance MCP reverse proxy."""

import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
import pytest
from agentarea_api.api.v1 import mcp_proxy
from agentarea_api.api.v1.mcp_proxy import (
    _authorize_mcp_tool_calls,
    _filter_inbound_headers,
    _filter_outbound_headers,
    _iter_jsonrpc_tool_calls,
    _MCPHeaderMismatchError,
    _resolve_upstream_url,
)
from agentarea_common.testing.flows import MainFlow
from agentarea_common.testing.mocks import TestSecretManager as InMemorySecrets
from agentarea_governance.domain.policies import EffectivePolicy, ToolsPolicy
from agentarea_mcp.application.service import MCPServerInstanceService
from agentarea_mcp.domain.mpc_server_instance_model import MCPServerInstance
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from starlette.requests import Request

# ----- _resolve_upstream_url -----


@pytest.mark.asyncio
async def test_resolve_upstream_url_url_type_from_server_remote_url():
    instance = SimpleNamespace(transport="url", json_spec={}, server_spec_id="x", id="i")
    server_spec = SimpleNamespace(
        remote_url="https://mcp.clickup.com/mcp",
        cmd=None,
        docker_image_url=None,
        json_spec={},
    )

    assert await _resolve_upstream_url(instance, server_spec) == (
        "https://mcp.clickup.com/mcp",
        "url",
    )


@pytest.mark.asyncio
async def test_resolve_upstream_url_docker_uses_manager_demand_gateway():
    instance = SimpleNamespace(
        transport="docker",
        json_spec={},
        endpoint_url="http://mcp-abc:8000",
        id="i",
    )
    server_spec = SimpleNamespace(remote_url=None, cmd=None, json_spec={})

    assert await _resolve_upstream_url(instance, server_spec) == (
        "http://mcp-manager:8000/mcp/i/mcp",
        "docker",
    )


@pytest.mark.asyncio
async def test_resolve_upstream_url_docker_ignores_stale_internal_url():
    instance = SimpleNamespace(
        transport="docker",
        json_spec={},
        endpoint_url="http://mcp-abc:8000/",
        id="i",
    )
    server_spec = SimpleNamespace(remote_url=None, cmd=None, json_spec={})

    assert await _resolve_upstream_url(instance, server_spec) == (
        "http://mcp-manager:8000/mcp/i/mcp",
        "docker",
    )


@pytest.mark.asyncio
async def test_resolve_upstream_url_url_type_returns_empty_without_remote_url():
    instance = SimpleNamespace(
        transport="url",
        json_spec={},
        id="i",
    )
    server_spec = SimpleNamespace(remote_url=None, cmd=None, docker_image_url=None, json_spec={})

    assert await _resolve_upstream_url(instance, server_spec) == ("", "url")


# ----- header filters -----


@pytest.mark.flow(MainFlow.MCP_PROXY)
def test_filter_inbound_drops_authorization_and_host():
    headers = {
        "Authorization": "Bearer user-token",
        "Host": "api.agentarea.dev",
        "Content-Type": "application/json",
        "Accept": "application/json,text/event-stream",
        "Mcp-Session-Id": "abc",
        "MCP-Protocol-Version": "2026-07-28",
        "Mcp-Method": "tools/call",
        "Mcp-Name": "github.create_issue",
    }

    out = _filter_inbound_headers(headers)

    assert "Authorization" not in out
    assert out["MCP-Protocol-Version"] == "2026-07-28"
    assert out["Mcp-Method"] == "tools/call"
    assert out["Mcp-Name"] == "github.create_issue"
    assert "Host" not in out
    assert out["Content-Type"] == "application/json"
    assert out["Mcp-Session-Id"] == "abc"


def test_filter_inbound_drops_hop_by_hop():
    headers = {
        "Connection": "close",
        "Transfer-Encoding": "chunked",
        "Upgrade": "websocket",
        "Content-Type": "application/json",
    }

    out = _filter_inbound_headers(headers)

    assert "Connection" not in out
    assert "Transfer-Encoding" not in out
    assert "Upgrade" not in out
    assert out["Content-Type"] == "application/json"


def test_filter_outbound_drops_content_length_and_transfer_encoding():
    # Upstream may send chunked or pre-sized; we let StreamingResponse manage these.
    headers = {
        "Content-Length": "123",
        "Transfer-Encoding": "chunked",
        "Content-Type": "text/event-stream",
        "Mcp-Session-Id": "abc",
    }

    out = _filter_outbound_headers(headers)

    assert "Content-Length" not in out
    assert "Transfer-Encoding" not in out
    assert out["Content-Type"] == "text/event-stream"
    assert out["Mcp-Session-Id"] == "abc"


def test_iter_jsonrpc_tool_calls_extracts_single_call():
    calls = _iter_jsonrpc_tool_calls(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "github.create_issue", "arguments": {"repo": "acme/app"}},
        }
    )

    assert calls == [("github.create_issue", {"repo": "acme/app"})]


def test_iter_jsonrpc_tool_calls_extracts_batch_calls_only():
    calls = _iter_jsonrpc_tool_calls(
        [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "slack.post_message", "arguments": {"channel": "eng"}},
            },
        ]
    )

    assert calls == [("slack.post_message", {"channel": "eng"})]


def test_iter_jsonrpc_tool_calls_ignores_non_calls():
    assert _iter_jsonrpc_tool_calls({"jsonrpc": "2.0", "method": "tools/list"}) == []


class _FakeResolver:
    """Stand in for GovernancePolicyResolver, returning a fixed snapshot."""

    def __init__(self, policy: EffectivePolicy):
        self._policy = policy

    async def resolve(self, **_kwargs) -> EffectivePolicy:
        return self._policy


def _install_policy(monkeypatch, policy: EffectivePolicy) -> None:
    monkeypatch.setattr(
        "agentarea_api.api.v1.mcp_proxy.GovernancePolicyResolver",
        lambda _repository_factory: _FakeResolver(policy),
    )


_INSTANCE = uuid4()
_CALL = (
    b'{"jsonrpc":"2.0","method":"tools/call",'
    b'"params":{"name":"github.create_issue","arguments":{"repo":"acme/app"}}}'
)


@pytest.mark.asyncio
async def test_authorize_mcp_tool_calls_allows_when_policy_permits(monkeypatch):
    # No governing policy — the proxy runs the same default-allow PDP as the task path.
    _install_policy(monkeypatch, EffectivePolicy())

    await _authorize_mcp_tool_calls(
        _CALL, SimpleNamespace(user_id="u1", workspace_id="ws1"), object(), instance_id=_INSTANCE
    )


@pytest.mark.asyncio
async def test_authorize_mcp_tool_calls_rejects_mismatched_name_header():
    body = (
        b'{"jsonrpc":"2.0","id":7,"method":"tools/call",'
        b'"params":{"name":"github.create_issue","arguments":{}}}'
    )

    with pytest.raises(_MCPHeaderMismatchError) as exc:
        await _authorize_mcp_tool_calls(
            body,
            SimpleNamespace(user_id="u1", workspace_id="ws1"),
            object(),
            instance_id=_INSTANCE,
            headers={"Mcp-Method": "tools/call", "Mcp-Name": "other"},
        )

    assert exc.value.body == {
        "jsonrpc": "2.0",
        "id": 7,
        "error": {
            "code": -32020,
            "message": "Header mismatch: Mcp-Name header value 'other' "
            "does not match body value 'github.create_issue'",
        },
    }


@pytest.mark.asyncio
async def test_authorize_mcp_tool_calls_accepts_base64_name_header(monkeypatch):
    _install_policy(monkeypatch, EffectivePolicy())
    encoded_name = "=?base64?" + base64.b64encode(b"github.create_issue").decode() + "?="

    await _authorize_mcp_tool_calls(
        _CALL,
        SimpleNamespace(user_id="u1", workspace_id="ws1"),
        object(),
        instance_id=_INSTANCE,
        headers={"Mcp-Method": "tools/call", "Mcp-Name": encoded_name},
    )


@pytest.mark.asyncio
async def test_authorize_mcp_tool_calls_rejects_headers_for_jsonrpc_batch():
    body = (
        b'[{"jsonrpc":"2.0","id":1,"method":"tools/call",'
        b'"params":{"name":"github.create_issue","arguments":{}}}]'
    )

    with pytest.raises(_MCPHeaderMismatchError) as exc:
        await _authorize_mcp_tool_calls(
            body,
            SimpleNamespace(user_id="u1", workspace_id="ws1"),
            object(),
            instance_id=_INSTANCE,
            headers={"Mcp-Method": "tools/call"},
        )

    assert exc.value.body["id"] is None
    assert exc.value.body["error"]["code"] == -32020


@pytest.mark.asyncio
async def test_authorize_mcp_tool_calls_leaves_header_less_batch_to_governance(monkeypatch):
    # A 2025-era client may batch and sends no routing headers: only the
    # policy decides, exactly as before 2026-07-28.
    _install_policy(monkeypatch, EffectivePolicy(tools=ToolsPolicy(denied=["github.create_issue"])))
    body = (
        b'[{"jsonrpc":"2.0","id":1,"method":"tools/list"},'
        b'{"jsonrpc":"2.0","id":2,"method":"tools/call",'
        b'"params":{"name":"github.create_issue","arguments":{}}}]'
    )

    with pytest.raises(HTTPException) as exc:
        await _authorize_mcp_tool_calls(
            body,
            SimpleNamespace(user_id="u1", workspace_id="ws1"),
            object(),
            instance_id=_INSTANCE,
            headers={"Content-Type": "application/json"},
        )

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_authorize_mcp_tool_calls_denies_when_policy_denies(monkeypatch):
    _install_policy(monkeypatch, EffectivePolicy(tools=ToolsPolicy(denied=["github.create_issue"])))

    with pytest.raises(HTTPException) as exc:
        await _authorize_mcp_tool_calls(
            _CALL,
            SimpleNamespace(user_id="u1", workspace_id="ws1"),
            object(),
            instance_id=_INSTANCE,
        )

    assert exc.value.status_code == 403
    assert "github.create_issue" in exc.value.detail


@pytest.mark.asyncio
async def test_a_rule_naming_the_tool_through_its_server_applies_at_the_proxy(monkeypatch):
    target = f"mcp:{_INSTANCE}:github.create_issue"
    _install_policy(monkeypatch, EffectivePolicy(tools=ToolsPolicy(denied=[target])))

    with pytest.raises(HTTPException) as exc:
        await _authorize_mcp_tool_calls(
            _CALL,
            SimpleNamespace(user_id="u1", workspace_id="ws1"),
            object(),
            instance_id=_INSTANCE,
        )
    assert exc.value.status_code == 403

    await _authorize_mcp_tool_calls(
        _CALL, SimpleNamespace(user_id="u1", workspace_id="ws1"), object(), instance_id=uuid4()
    )


def test_member_upstream_never_sees_caller_cookies_nor_sets_ours():
    """A URL-type upstream is member-supplied: the caller's cookies and forwarding
    headers must not reach it, and its Set-Cookie must not land on the API origin."""
    inbound = _filter_inbound_headers(
        {
            "Cookie": "ory_kratos_session=secret",
            "X-Forwarded-For": "10.0.0.1",
            "Accept": "application/json",
        }
    )
    outbound = _filter_outbound_headers(
        {"Set-Cookie": "session=x; Domain=.agentarea.dev", "Content-Type": "application/json"}
    )

    assert inbound == {"Accept": "application/json"}
    assert outbound == {"Content-Type": "application/json"}


@pytest.mark.asyncio
async def test_the_upstream_receives_the_connections_stored_secret_header(monkeypatch):
    """A URL connection's credential header lives in the secret store, not in
    json_spec; the proxied request must still carry it upstream."""
    endpoint = "https://mcp.example.com/mcp"
    server = SimpleNamespace(
        remote_url=endpoint,
        cmd=None,
        docker_image_url=None,
        json_spec={"type": "url", "endpoint_url": endpoint},
    )
    instance = MCPServerInstance(
        name="remote",
        server_spec_id="spec",
        transport="url",
        json_spec={"headers": {}, "env_vars": ["X-Api-Key"]},
    )
    instance.id = uuid4()

    with patch("agentarea_mcp.application.service.get_database", MagicMock()):
        service = MCPServerInstanceService(
            repository_factory=MagicMock(),
            event_broker=MagicMock(),
            secret_manager=InMemorySecrets(),
        )
    service.mcp_server_repository = SimpleNamespace(get_server_by_id=AsyncMock(return_value=server))
    await service.env_service.set_instance_environment(instance.id, {"X-Api-Key": "canary"})

    monkeypatch.setattr(
        mcp_proxy,
        "MCPServerInstanceRepository",
        lambda *_: SimpleNamespace(get_by_id=AsyncMock(return_value=instance)),
    )
    monkeypatch.setattr(
        mcp_proxy,
        "MCPServerRepository",
        lambda *_: SimpleNamespace(get_server_by_id=AsyncMock(return_value=server)),
    )
    monkeypatch.setattr(
        mcp_proxy, "_guard_and_pin_upstream", lambda url, *_args, **_kw: (url, None, None)
    )
    received: list[httpx.Request] = []

    def upstream(request: httpx.Request) -> httpx.Response:
        received.append(request)
        return httpx.Response(200, stream=httpx.ByteStream(b"{}"))

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        mcp_proxy.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(upstream), **kwargs),
    )
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": f"/v1/mcp/{instance.id}/mcp",
            "headers": [(b"accept", b"text/event-stream")],
            "query_string": b"",
        }
    )

    response = await mcp_proxy.proxy_instance(
        instance.id,
        request,
        MagicMock(user_id="u1", workspace_id="ws1"),
        MagicMock(),
        InMemorySecrets(),
        service,
    )
    assert isinstance(response, StreamingResponse)
    async for _ in response.body_iterator:
        pass

    (sent,) = received
    assert sent.headers["x-api-key"] == "canary"
