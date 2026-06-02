"""ToolManager honoring load_mode for OpenAPI tools (split discovery)."""

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from agentarea_agents_sdk.tools.tool_manager import DiscoveryResult, ToolManager


class _FakeOpenAPIService:
    """Minimal stand-in for OpenAPIConnectionService."""

    def __init__(self, connection):
        self._connection = connection

    async def get_connection(self, connection_id):
        if str(connection_id) == str(self._connection.id):
            return self._connection
        return None

    async def list_connections(self, search=None):
        if not search or self._connection.name == search:
            return [self._connection], 1
        return [], 0


def _make_connection(num_ops: int = 3, name: str = "stripe-api"):
    """Build a connection with both `available_tools` (for searchable path)
    and a real spec_content (for explicit path which re-parses)."""
    available_tools = [
        {
            "name": f"op_{i:02d}",
            "description": f"Operation {i}",
            "inputSchema": {
                "type": "object",
                "properties": {"x": {"type": "string"}},
                "required": [],
            },
        }
        for i in range(num_ops)
    ]
    paths = {
        f"/op/{i:02d}": {
            "get": {
                "operationId": f"op_{i:02d}",
                "summary": f"Operation {i}",
                "parameters": [{"name": "x", "in": "query", "schema": {"type": "string"}}],
                "responses": {"200": {"description": "ok"}},
            }
        }
        for i in range(num_ops)
    }
    return SimpleNamespace(
        id=uuid4(),
        name=name,
        spec_content={"openapi": "3.0.0", "info": {"title": name, "version": "1"}, "paths": paths},
        available_tools=available_tools,
    )


@pytest.mark.asyncio
async def test_searchable_load_mode_routes_to_searchable_entries():
    conn = _make_connection(num_ops=5)
    svc = _FakeOpenAPIService(conn)
    manager = ToolManager(openapi_connection_service=svc)

    tools_config = [
        {
            "type": "openapi",
            "name": conn.name,
            "settings": {
                "openapi_connection_id": str(conn.id),
                "load_mode": "searchable",
            },
        }
    ]
    result = await manager.discover_available_tools_split(
        agent_id=UUID("11111111-1111-1111-1111-111111111111"),
        tools_config=tools_config,
        mcp_server_instance_service=None,
    )
    assert isinstance(result, DiscoveryResult)
    # No openapi schemas in explicit (only the built-in completion remains).
    explicit_names = {t["function"]["name"] for t in result.explicit_tools}
    assert "completion" in explicit_names
    assert not any(name.startswith("op_") for name in explicit_names)
    # All 5 operations land in the searchable pool with full ToolCandidate shape.
    assert len(result.searchable_entries) == 5
    entry = result.searchable_entries[0]
    assert entry["name"].startswith("op_")
    assert entry["description"].startswith("Operation")
    assert entry["connection_id"] == str(conn.id)
    assert entry["source_type"] == "openapi"
    assert entry["schema"]["type"] == "function"
    assert entry["schema"]["function"]["parameters"]["type"] == "object"


@pytest.mark.asyncio
async def test_explicit_load_mode_keeps_full_schemas_in_explicit():
    conn = _make_connection(num_ops=3)
    svc = _FakeOpenAPIService(conn)
    manager = ToolManager(openapi_connection_service=svc)

    tools_config = [
        {
            "type": "openapi",
            "name": conn.name,
            "settings": {
                "openapi_connection_id": str(conn.id),
                "load_mode": "explicit",
            },
        }
    ]
    result = await manager.discover_available_tools_split(
        agent_id=UUID("11111111-1111-1111-1111-111111111111"),
        tools_config=tools_config,
        mcp_server_instance_service=None,
    )
    assert result.searchable_entries == []
    op_names = {
        t["function"]["name"]
        for t in result.explicit_tools
        if t["function"]["name"].startswith("op_")
    }
    assert op_names == {"op_00", "op_01", "op_02"}


@pytest.mark.asyncio
async def test_missing_load_mode_treated_as_explicit():
    conn = _make_connection(num_ops=2)
    svc = _FakeOpenAPIService(conn)
    manager = ToolManager(openapi_connection_service=svc)

    tools_config = [
        {
            "type": "openapi",
            "name": conn.name,
            "settings": {"openapi_connection_id": str(conn.id)},
        }
    ]
    result = await manager.discover_available_tools_split(
        agent_id=UUID("11111111-1111-1111-1111-111111111111"),
        tools_config=tools_config,
        mcp_server_instance_service=None,
    )
    assert result.searchable_entries == []
    op_names = {
        t["function"]["name"]
        for t in result.explicit_tools
        if t["function"]["name"].startswith("op_")
    }
    assert op_names == {"op_00", "op_01"}


@pytest.mark.asyncio
async def test_legacy_discover_available_tools_ignores_load_mode():
    """Old API ignores load_mode and always returns full schemas (back-compat)."""
    conn = _make_connection(num_ops=2)
    svc = _FakeOpenAPIService(conn)
    manager = ToolManager(openapi_connection_service=svc)

    tools_config = [
        {
            "type": "openapi",
            "name": conn.name,
            "settings": {
                "openapi_connection_id": str(conn.id),
                "load_mode": "searchable",  # would normally defer
            },
        }
    ]
    flat = await manager.discover_available_tools(
        agent_id=UUID("11111111-1111-1111-1111-111111111111"),
        tools_config=tools_config,
        mcp_server_instance_service=None,
    )
    assert isinstance(flat, list)
    op_names = {t["function"]["name"] for t in flat if t["function"]["name"].startswith("op_")}
    assert op_names == {"op_00", "op_01"}


@pytest.mark.asyncio
async def test_searchable_filters_by_allowed_tools():
    conn = _make_connection(num_ops=4)
    svc = _FakeOpenAPIService(conn)
    manager = ToolManager(openapi_connection_service=svc)

    tools_config = [
        {
            "type": "openapi",
            "name": conn.name,
            "settings": {
                "openapi_connection_id": str(conn.id),
                "load_mode": "searchable",
                "allowed_tools": ["op_01", "op_03"],
            },
        }
    ]
    result = await manager.discover_available_tools_split(
        agent_id=UUID("11111111-1111-1111-1111-111111111111"),
        tools_config=tools_config,
        mcp_server_instance_service=None,
    )
    assert {e["name"] for e in result.searchable_entries} == {"op_01", "op_03"}


@pytest.mark.asyncio
async def test_no_openapi_service_yields_no_searchable_entries():
    manager = ToolManager(openapi_connection_service=None)
    tools_config = [
        {
            "type": "openapi",
            "name": "some-api",
            "settings": {"load_mode": "searchable"},
        }
    ]
    result = await manager.discover_available_tools_split(
        agent_id=UUID("11111111-1111-1111-1111-111111111111"),
        tools_config=tools_config,
        mcp_server_instance_service=None,
    )
    assert result.searchable_entries == []


@pytest.mark.asyncio
async def test_empty_tools_config_returns_only_builtins():
    manager = ToolManager()
    result = await manager.discover_available_tools_split(
        agent_id=UUID("11111111-1111-1111-1111-111111111111"),
        tools_config=None,
        mcp_server_instance_service=None,
    )
    assert result.searchable_entries == []
    assert any(t["function"]["name"] == "completion" for t in result.explicit_tools)
