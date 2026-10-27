"""A platform-managed connection never shows a tenant where it runs.

The operator points platform connections at an in-cluster gateway route
(``http://agentarea-llm-gateway.agentarea.svc.cluster.local:8080/tools/...``).
Every workspace can read and call them, so their address must not reach the
response: the same rule as a platform provider configuration's endpoint.
"""

import uuid
from datetime import UTC, datetime

from agentarea_api.api.v1.mcp_servers_specifications import MCPServerResponse
from agentarea_api.api.v1.openapi_connections import _connection_response
from agentarea_api.tools.mcp_servers_toolset import _serialize_server
from agentarea_api.tools.openapi_connections_toolset import _serialize
from agentarea_common.constants import MANAGED_BY_PLATFORM, PLATFORM_WORKSPACE_ID
from agentarea_mcp.domain.models import MCPServer
from agentarea_openapi.domain.models import OpenAPIConnection

NOW = datetime(2026, 1, 1, tzinfo=UTC)
GATEWAY = "http://agentarea-llm-gateway.agentarea.svc.cluster.local:8080/tools/yandex-search"


def _openapi(managed_by: str | None, base_url: str) -> OpenAPIConnection:
    conn = OpenAPIConnection(
        name="Yandex Search",
        base_url=base_url,
        spec_url="https://catalog.example.test/yandex-search/openapi.json",
        id=uuid.uuid4(),
        created_at=NOW,
        updated_at=NOW,
        workspace_id="ws-1",
    )
    conn.managed_by = managed_by
    return conn


def _mcp_spec(workspace_id: str, registry_item_id: uuid.UUID | None, url: str) -> MCPServer:
    return MCPServer(
        name="Example MCP",
        description="",
        slug="example-mcp",
        status="active",
        remote_url=url,
        registry_item_id=registry_item_id,
        json_spec={"name": "example", "remotes": [{"type": "streamable-http", "url": url}]},
        id=uuid.uuid4(),
        created_at=NOW,
        updated_at=NOW,
        workspace_id=workspace_id,
    )


def test_a_platform_openapi_connection_hides_its_base_url():
    conn = _openapi(MANAGED_BY_PLATFORM, GATEWAY)

    response = _connection_response(conn)

    assert response.base_url is None
    assert response.managed_by == MANAGED_BY_PLATFORM
    assert response.spec_url == conn.spec_url
    assert _serialize(conn)["base_url"] is None


def test_a_workspace_openapi_connection_keeps_its_base_url():
    conn = _openapi(None, "https://api.example.test/v1")

    assert _connection_response(conn).base_url == "https://api.example.test/v1"
    assert _serialize(conn)["base_url"] == "https://api.example.test/v1"


def test_the_spec_behind_a_platform_mcp_connection_hides_its_address():
    spec = _mcp_spec(PLATFORM_WORKSPACE_ID, None, GATEWAY)

    response = MCPServerResponse.from_domain(spec)

    assert response.remote_url is None
    assert response.json_spec == {"name": "example", "remotes": [{"type": "streamable-http"}]}
    assert GATEWAY not in response.model_dump_json()
    assert _serialize_server(spec)["remote_url"] is None


def test_a_catalog_mirror_and_a_workspace_spec_keep_their_address():
    url = "https://mcp.example.test/mcp"
    for spec in (
        _mcp_spec(PLATFORM_WORKSPACE_ID, uuid.uuid4(), url),
        _mcp_spec("ws-1", None, url),
    ):
        response = MCPServerResponse.from_domain(spec)

        assert response.remote_url == url
        assert response.json_spec is not None
        assert response.json_spec["remotes"][0]["url"] == url
