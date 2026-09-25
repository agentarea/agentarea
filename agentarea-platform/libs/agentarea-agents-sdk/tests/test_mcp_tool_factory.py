"""Tests for MCP tool factory visibility filtering."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from agentarea_agents_sdk.tools.mcp_tool import MCPToolFactory


class _Service:
    def __init__(self, instance):
        self.instance = instance

    async def get(self, _instance_id):
        return self.instance


@pytest.mark.asyncio
async def test_factory_drops_tools_visible_only_to_apps():
    instance_id = uuid4()
    instance = SimpleNamespace(
        verification={"status": "succeeded"},
        json_spec={},
        tools=[
            {
                "name": "show",
                "description": "Show the app",
                "inputSchema": {"type": "object"},
                "_meta": {"ui": {"resourceUri": "ui://show"}},
            },
            {
                "name": "refresh",
                "description": "Refresh app state",
                "inputSchema": {"type": "object"},
                "_meta": {"ui": {"resourceUri": "ui://refresh", "visibility": ["app"]}},
            },
        ],
    )

    tools = await MCPToolFactory.create_tools_from_server(instance_id, _Service(instance))

    assert [tool.name for tool in tools] == ["show"]
