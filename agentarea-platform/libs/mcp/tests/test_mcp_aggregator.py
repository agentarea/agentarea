"""Unit tests for the MCP aggregator proxy (namespacing + call routing)."""

import inspect

import pytest

from agentarea_mcp.application.mcp_aggregator import AggregatedMember, MCPAggregatorProxy


def _proxy(members, names=None):
    return MCPAggregatorProxy(
        name="c",
        description="",
        members=members,
        instance_urls={str(m.mcp_instance_id): "http://mcp-x:8000" for m in members},
        instance_names=names or {},
    )


def test_namespace_prefers_explicit_prefix():
    m = AggregatedMember(mcp_instance_id="1", namespace_prefix="gh")
    assert _proxy([m])._get_namespace(m) == "gh"


def test_namespace_falls_back_to_slugified_instance_name():
    m = AggregatedMember(mcp_instance_id="1")
    p = _proxy([m], names={"1": "My Server"})
    assert p._get_namespace(m) == "my_server"


def test_namespace_falls_back_to_id_prefix():
    m = AggregatedMember(mcp_instance_id="abcdef12-3456")
    assert _proxy([m])._get_namespace(m) == "abcdef12"


@pytest.mark.parametrize(
    "url,expected",
    [
        # Bare URL: honor as-given first (root-streamable remotes like Vercel),
        # then fall back to the /mcp sibling (internal mcp-bridge containers).
        ("http://mcp-x:8000", ["http://mcp-x:8000", "http://mcp-x:8000/mcp"]),
        ("http://mcp-x:8000/", ["http://mcp-x:8000", "http://mcp-x:8000/mcp"]),
        # Explicit /mcp: use exactly that.
        ("http://mcp-x:8000/mcp", ["http://mcp-x:8000/mcp"]),
        # Explicit /sse: aggregator is streamable-only, map to the /mcp sibling.
        ("http://mcp-x:8000/sse", ["http://mcp-x:8000/mcp"]),
    ],
)
def test_streamable_candidates_normalization(url, expected):
    assert MCPAggregatorProxy._streamable_candidates(url) == expected


def test_proxy_handler_signature_from_input_schema():
    p = _proxy([AggregatedMember(mcp_instance_id="1")])
    h = p._make_proxy_handler(
        AggregatedMember(mcp_instance_id="1"),
        "search",
        {"properties": {"q": {"type": "string"}}, "required": ["q"]},
    )
    sig = inspect.signature(h)
    assert "q" in sig.parameters
    assert sig.parameters["q"].annotation is str


async def test_call_namespaced_tool_routes_to_owning_member(monkeypatch):
    members = [
        AggregatedMember(mcp_instance_id="1", namespace_prefix="gh"),
        AggregatedMember(mcp_instance_id="2", namespace_prefix="lin"),
    ]
    p = _proxy(members)
    calls = []

    async def fake_call(member, tool_name, arguments):
        calls.append((member.namespace_prefix, tool_name, arguments))
        return "ok"

    monkeypatch.setattr(p, "_call_member_tool", fake_call)

    result = await p.call_namespaced_tool("lin__create_ticket", {"x": 1})
    assert result == "ok"
    assert calls == [("lin", "create_ticket", {"x": 1})]


async def test_call_namespaced_tool_unknown_raises():
    p = _proxy([AggregatedMember(mcp_instance_id="1", namespace_prefix="gh")])
    with pytest.raises(ValueError):
        await p.call_namespaced_tool("nope__x", {})
