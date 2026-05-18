"""Tests for ToolManager openapi branch and unknown-type warning."""

import logging
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from agentarea_agents_sdk.tools.tool_manager import ToolManager


def _patch_validate_url():
    """Patch SSRF validator to avoid DNS resolution in unit tests."""
    return patch(
        "agentarea_openapi.application.url_validator.validate_url",
        return_value=[],
    )


_MINIMAL_SPEC = {
    "openapi": "3.0.0",
    "info": {"title": "Mini", "version": "1.0.0"},
    "paths": {
        "/items": {"get": {"operationId": "listItems", "summary": "List"}},
        "/items/{id}": {"delete": {"operationId": "deleteItem", "summary": "Delete"}},
    },
}


def _make_connection(name="my-api", spec_content=None):
    return SimpleNamespace(
        id=uuid4(),
        name=name,
        base_url="https://api.example.com",
        spec_content=spec_content or _MINIMAL_SPEC,
        custom_headers=[],
        auth_config_id=None,
    )


def _make_openapi_service(connection=None):
    svc = AsyncMock()
    conn = connection or _make_connection()
    svc.get_connection = AsyncMock(return_value=conn)
    svc.list_connections = AsyncMock(return_value=([conn], 1))
    svc.resolve_headers = AsyncMock(return_value={})
    svc._allow_private_urls = False
    return svc


class TestToolManagerOpenAPIBranch:
    @pytest.mark.asyncio
    async def test_openapi_tools_discovered(self):
        """discover_available_tools should include OpenAPI tools."""
        openapi_svc = _make_openapi_service()
        mcp_svc = AsyncMock()

        tools_config = [
            {"type": "openapi", "name": "my-api", "settings": {}},
        ]

        manager = ToolManager(openapi_connection_service=openapi_svc)
        result = await manager.discover_available_tools(
            agent_id=uuid4(),
            tools_config=tools_config,
            mcp_server_instance_service=mcp_svc,
        )

        openapi_tool_defs = [
            t for t in result
            if t.get("function", {}).get("name") in ("listItems", "deleteItem")
        ]
        assert len(openapi_tool_defs) == 2

    @pytest.mark.asyncio
    async def test_openapi_tools_filtered_by_allowed_tools(self):
        """allowed_tools setting should filter which operations are exposed."""
        openapi_svc = _make_openapi_service()
        mcp_svc = AsyncMock()

        tools_config = [
            {
                "type": "openapi",
                "name": "my-api",
                "settings": {"allowed_tools": ["listItems"]},
            }
        ]

        manager = ToolManager(openapi_connection_service=openapi_svc)
        result = await manager.discover_available_tools(
            agent_id=uuid4(),
            tools_config=tools_config,
            mcp_server_instance_service=mcp_svc,
        )

        names = [t.get("function", {}).get("name") for t in result]
        assert "listItems" in names
        assert "deleteItem" not in names

    @pytest.mark.asyncio
    async def test_openapi_allowed_tools_dict_form(self):
        """allowed_tools can also be [{tool_name: ...}] dicts."""
        openapi_svc = _make_openapi_service()
        mcp_svc = AsyncMock()

        tools_config = [
            {
                "type": "openapi",
                "name": "my-api",
                "settings": {"allowed_tools": [{"tool_name": "listItems"}]},
            }
        ]

        manager = ToolManager(openapi_connection_service=openapi_svc)
        result = await manager.discover_available_tools(
            agent_id=uuid4(),
            tools_config=tools_config,
            mcp_server_instance_service=mcp_svc,
        )

        names = [t.get("function", {}).get("name") for t in result]
        assert "listItems" in names
        assert "deleteItem" not in names

    @pytest.mark.asyncio
    async def test_openapi_skipped_without_service(self):
        """Without openapi_connection_service, no openapi tools are added (no crash)."""
        mcp_svc = AsyncMock()

        tools_config = [
            {"type": "openapi", "name": "my-api", "settings": {}},
        ]

        manager = ToolManager()  # no openapi_connection_service
        result = await manager.discover_available_tools(
            agent_id=uuid4(),
            tools_config=tools_config,
            mcp_server_instance_service=mcp_svc,
        )

        # Should only have built-in tools, no openapi tools
        openapi_names = {"listItems", "deleteItem"}
        result_names = {t.get("function", {}).get("name") for t in result}
        assert result_names.isdisjoint(openapi_names)

    @pytest.mark.asyncio
    async def test_unknown_tool_type_logs_warning(self, caplog):
        """Unknown tool types should log a warning instead of silently skipping."""
        mcp_svc = AsyncMock()

        tools_config = [
            {"type": "unknown_exotic_type", "name": "mystery", "settings": {}},
        ]

        manager = ToolManager()
        with caplog.at_level(logging.WARNING, logger="agentarea_agents_sdk.tools.tool_manager"):
            await manager.discover_available_tools(
                agent_id=uuid4(),
                tools_config=tools_config,
                mcp_server_instance_service=mcp_svc,
            )

        assert any("unknown_exotic_type" in r.message.lower() or "unknown tool type" in r.message.lower() for r in caplog.records)

    @pytest.mark.asyncio
    async def test_openapi_providers_discovered(self):
        """discover_tool_providers should include OpenAPIToolProvider."""
        openapi_svc = _make_openapi_service()
        mcp_svc = AsyncMock()

        tools_config = [
            {"type": "openapi", "name": "my-api", "settings": {}},
        ]

        manager = ToolManager(openapi_connection_service=openapi_svc)
        providers = await manager.discover_tool_providers(
            agent_id=uuid4(),
            tools_config=tools_config,
            mcp_server_instance_service=mcp_svc,
        )

        openapi_providers = [p for p in providers if p.provider_type == "openapi"]
        assert len(openapi_providers) == 1
        assert openapi_providers[0].name == "my-api"

    @pytest.mark.asyncio
    async def test_openapi_provider_catalog_entry(self):
        """OpenAPIToolProvider catalog entry lists discovered tool names."""
        openapi_svc = _make_openapi_service()
        mcp_svc = AsyncMock()

        tools_config = [
            {"type": "openapi", "name": "my-api", "settings": {}},
        ]

        manager = ToolManager(openapi_connection_service=openapi_svc)
        providers = await manager.discover_tool_providers(
            agent_id=uuid4(),
            tools_config=tools_config,
            mcp_server_instance_service=mcp_svc,
        )

        openapi_provider = next(p for p in providers if p.provider_type == "openapi")
        catalog = openapi_provider.get_catalog_entry()
        assert catalog.provider_type == "openapi"
        assert "listItems" in catalog.tool_names
        assert "deleteItem" in catalog.tool_names

    @pytest.mark.asyncio
    async def test_backward_compatible_no_openapi_service(self):
        """Existing callers that don't pass openapi_connection_service continue to work."""
        mcp_svc = AsyncMock()

        manager = ToolManager()
        result = await manager.discover_available_tools(
            agent_id=uuid4(),
            tools_config=None,
            mcp_server_instance_service=mcp_svc,
        )

        assert isinstance(result, list)
        assert len(result) >= 1  # At least completion tool
