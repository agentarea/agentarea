from types import SimpleNamespace

import pytest
from agentarea_api.api.v1.mcp_oauth_connect import (
    _instance_detail_url,
    _resolve_instance_remote_url,
)
from agentarea_common.testing.flows import MainFlow


@pytest.mark.flow(MainFlow.MCP_OAUTH)
def test_resolve_instance_remote_url_uses_server_spec_remote_url():
    server_spec = SimpleNamespace(remote_url="https://server.example/mcp", json_spec={})

    assert _resolve_instance_remote_url(server_spec) == "https://server.example/mcp"


def test_resolve_instance_remote_url_uses_server_spec_json_fallback():
    server_spec = SimpleNamespace(
        remote_url=None,
        json_spec={"type": "url", "endpoint_url": "https://json-spec.example/mcp"},
    )

    assert _resolve_instance_remote_url(server_spec) == "https://json-spec.example/mcp"


def test_resolve_instance_remote_url_returns_none_without_remote_url():
    server_spec = SimpleNamespace(remote_url=None, json_spec={"type": "docker"})

    assert _resolve_instance_remote_url(server_spec) is None


@pytest.mark.flow(MainFlow.MCP_OAUTH)
def test_callback_returns_the_user_to_the_connection_page():
    """The page an MCP instance is shown on is /connections, not the retired
    /mcp-servers — a user finishing OAuth must land on their connection."""
    detail = _instance_detail_url("https://app.example", "d50241d7-eafe-4011-8479-b40f7a2aab3c")

    assert detail == "https://app.example/connections/d50241d7-eafe-4011-8479-b40f7a2aab3c"
