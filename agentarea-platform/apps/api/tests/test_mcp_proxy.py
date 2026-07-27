"""Unit tests for the per-instance MCP reverse proxy."""

from types import SimpleNamespace

import pytest
from agentarea_api.api.v1.mcp_proxy import (
    _authorize_mcp_tool_calls,
    _ensure_provisioned,
    _filter_inbound_headers,
    _filter_outbound_headers,
    _iter_jsonrpc_tool_calls,
    _resolve_upstream_url,
)
from agentarea_common.testing.flows import MainFlow
from agentarea_governance.domain.policies import EffectivePolicy, ToolsPolicy
from fastapi import HTTPException

# ----- _resolve_upstream_url -----


@pytest.mark.asyncio
async def test_resolve_upstream_url_url_type_from_server_remote_url():
    instance = SimpleNamespace(json_spec={}, server_spec_id="x", id="i")
    server_spec = SimpleNamespace(
        remote_url="https://mcp.clickup.com/mcp",
        cmd=None,
        json_spec={},
    )

    assert await _resolve_upstream_url(instance, server_spec) == (
        "https://mcp.clickup.com/mcp",
        "url",
    )


@pytest.mark.asyncio
async def test_resolve_upstream_url_docker_appends_mcp_path():
    instance = SimpleNamespace(
        json_spec={"type": "docker"},
        endpoint_url="http://mcp-abc:8000",
        id="i",
    )
    server_spec = SimpleNamespace(remote_url=None, cmd=None, json_spec={})

    assert await _resolve_upstream_url(instance, server_spec) == (
        "http://mcp-abc:8000/mcp",
        "docker",
    )


@pytest.mark.asyncio
async def test_resolve_upstream_url_docker_strips_trailing_slash():
    instance = SimpleNamespace(
        json_spec={"type": "docker"},
        endpoint_url="http://mcp-abc:8000/",
        id="i",
    )
    server_spec = SimpleNamespace(remote_url=None, cmd=None, json_spec={})

    assert await _resolve_upstream_url(instance, server_spec) == (
        "http://mcp-abc:8000/mcp",
        "docker",
    )


@pytest.mark.asyncio
async def test_resolve_upstream_url_url_type_returns_empty_without_remote_url():
    instance = SimpleNamespace(
        json_spec={"type": "url"},
        id="i",
    )
    server_spec = SimpleNamespace(remote_url=None, cmd=None, json_spec={})

    assert await _resolve_upstream_url(instance, server_spec) == ("", "url")


# ----- lazy re-provisioning -----


class _SpyInstanceService:
    def __init__(self):
        self.verified = []

    async def verify_instance(self, instance_id):
        self.verified.append(instance_id)
        return {"status": "succeeded"}


class _SpySession:
    def __init__(self):
        self.refreshed = []

    async def refresh(self, instance):
        self.refreshed.append(instance)


def _lazy_instance(verification_status: str, *, lazy: bool = True):
    return SimpleNamespace(
        id="9f1c1a3e-0000-4000-8000-000000000001",
        json_spec={"type": "docker", "lazy_provisioning": lazy},
        verification={"schema_version": 1, "status": verification_status},
    )


@pytest.mark.asyncio
async def test_ensure_provisioned_starts_a_stopped_lazy_instance(monkeypatch):
    # An idle instance that the reaper stopped comes back as never_attempted;
    # a proxied call has to start it again rather than dispatch into nothing.
    monkeypatch.setenv("MCP_LAZY_PROVISIONING_ENABLED", "true")
    service, session = _SpyInstanceService(), _SpySession()
    instance = _lazy_instance("never_attempted")

    await _ensure_provisioned(instance, service, session)

    assert service.verified == [instance.id]
    # Without the refresh the proxy would resolve the upstream from the spec as
    # it looked before provisioning.
    assert session.refreshed == [instance]


@pytest.mark.asyncio
async def test_ensure_provisioned_leaves_a_running_instance_alone(monkeypatch):
    monkeypatch.setenv("MCP_LAZY_PROVISIONING_ENABLED", "true")
    service, session = _SpyInstanceService(), _SpySession()

    await _ensure_provisioned(_lazy_instance("succeeded"), service, session)

    assert service.verified == []


@pytest.mark.asyncio
async def test_ensure_provisioned_does_not_start_eager_instances(monkeypatch):
    # An eagerly-provisioned instance is never reaped, so a failed verification
    # is a real failure — starting it here would paper over it.
    monkeypatch.setenv("MCP_LAZY_PROVISIONING_ENABLED", "true")
    service, session = _SpyInstanceService(), _SpySession()

    await _ensure_provisioned(_lazy_instance("failed", lazy=False), service, session)

    assert service.verified == []


@pytest.mark.asyncio
async def test_ensure_provisioned_respects_the_feature_flag(monkeypatch):
    monkeypatch.setenv("MCP_LAZY_PROVISIONING_ENABLED", "false")
    service, session = _SpyInstanceService(), _SpySession()

    await _ensure_provisioned(_lazy_instance("never_attempted"), service, session)

    assert service.verified == []


# ----- header filters -----


@pytest.mark.flow(MainFlow.MCP_PROXY)
def test_filter_inbound_drops_authorization_and_host():
    headers = {
        "Authorization": "Bearer user-token",
        "Host": "api.agentarea.dev",
        "Content-Type": "application/json",
        "Accept": "application/json,text/event-stream",
        "Mcp-Session-Id": "abc",
    }

    out = _filter_inbound_headers(headers)

    assert "Authorization" not in out
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


_CALL = (
    b'{"jsonrpc":"2.0","method":"tools/call",'
    b'"params":{"name":"github.create_issue","arguments":{"repo":"acme/app"}}}'
)


@pytest.mark.asyncio
async def test_authorize_mcp_tool_calls_allows_when_policy_permits(monkeypatch):
    # No governing policy — the proxy runs the same default-allow PDP as the task path.
    _install_policy(monkeypatch, EffectivePolicy())

    await _authorize_mcp_tool_calls(
        _CALL, SimpleNamespace(user_id="u1", workspace_id="ws1"), object()
    )


@pytest.mark.asyncio
async def test_authorize_mcp_tool_calls_denies_when_policy_denies(monkeypatch):
    _install_policy(monkeypatch, EffectivePolicy(tools=ToolsPolicy(denied=["github.create_issue"])))

    with pytest.raises(HTTPException) as exc:
        await _authorize_mcp_tool_calls(
            _CALL, SimpleNamespace(user_id="u1", workspace_id="ws1"), object()
        )

    assert exc.value.status_code == 403
    assert "github.create_issue" in exc.value.detail
