from types import SimpleNamespace

from agentarea_api.api.v1.mcp_oauth_connect import _resolve_instance_remote_url


def test_resolve_instance_remote_url_uses_instance_legacy_endpoint_url():
    instance = SimpleNamespace(json_spec={"endpoint_url": "https://instance.example/mcp"})
    server_spec = SimpleNamespace(remote_url="https://server.example/mcp", json_spec={})

    assert _resolve_instance_remote_url(instance, server_spec) == "https://instance.example/mcp"


def test_resolve_instance_remote_url_uses_server_spec_remote_url():
    instance = SimpleNamespace(json_spec={"headers": {"Authorization": "Bearer token"}})
    server_spec = SimpleNamespace(remote_url="https://server.example/mcp", json_spec={})

    assert _resolve_instance_remote_url(instance, server_spec) == "https://server.example/mcp"


def test_resolve_instance_remote_url_uses_server_spec_json_fallback():
    instance = SimpleNamespace(json_spec={})
    server_spec = SimpleNamespace(
        remote_url=None,
        json_spec={"type": "url", "endpoint_url": "https://json-spec.example/mcp"},
    )

    assert _resolve_instance_remote_url(instance, server_spec) == "https://json-spec.example/mcp"


def test_resolve_instance_remote_url_returns_none_without_remote_url():
    instance = SimpleNamespace(json_spec={"headers": {}})
    server_spec = SimpleNamespace(remote_url=None, json_spec={"type": "docker"})

    assert _resolve_instance_remote_url(instance, server_spec) is None
