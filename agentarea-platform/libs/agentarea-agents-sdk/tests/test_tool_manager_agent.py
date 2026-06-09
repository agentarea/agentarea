"""Tests for ToolManager agent tool discovery."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from agentarea_agents_sdk.tools.tool_manager import ToolManager


def _make_mock_agent(agent_id="agent-123", name="researcher", description="Researches topics"):
    return SimpleNamespace(id=agent_id, name=name, description=description)


class TestToolManagerAgentDiscovery:
    """Tests for discover_available_tools with type='agent' configs."""

    @pytest.mark.asyncio
    async def test_agent_tool_added_to_discovered_tools(self):
        """Agent tools should be discovered and added via AgentToolFactory."""
        agent_service = AsyncMock()
        agent_service.get_by_name = AsyncMock(return_value=_make_mock_agent())
        mcp_service = AsyncMock()

        tools_config = [
            {"type": "agent", "name": "researcher", "settings": {}},
        ]

        manager = ToolManager()
        result = await manager.discover_available_tools(
            agent_id=uuid4(),
            tools_config=tools_config,
            mcp_server_instance_service=mcp_service,
            agent_service=agent_service,
            base_url="http://localhost:8000/api/v1",
        )

        # Should have built-in (completion) + agent tool
        agent_tool_defs = [
            t for t in result if t.get("function", {}).get("name", "").startswith("delegate_to_")
        ]
        assert len(agent_tool_defs) == 1
        assert agent_tool_defs[0]["function"]["name"] == "delegate_to_researcher"
        agent_service.get_by_name.assert_awaited_once_with("researcher")

    @pytest.mark.asyncio
    async def test_agent_tool_skipped_without_agent_service(self):
        """Agent tools should be skipped when agent_service is not provided."""
        mcp_service = AsyncMock()

        tools_config = [
            {"type": "agent", "name": "researcher", "settings": {}},
        ]

        manager = ToolManager()
        result = await manager.discover_available_tools(
            agent_id=uuid4(),
            tools_config=tools_config,
            mcp_server_instance_service=mcp_service,
            # No agent_service or base_url
        )

        # Should only have built-in tools (no agent tools)
        agent_tool_defs = [
            t for t in result if t.get("function", {}).get("name", "").startswith("delegate_to_")
        ]
        assert len(agent_tool_defs) == 0

    @pytest.mark.asyncio
    async def test_agent_tool_skipped_without_base_url(self):
        """Agent tools should be skipped when base_url is empty."""
        agent_service = AsyncMock()
        mcp_service = AsyncMock()

        tools_config = [
            {"type": "agent", "name": "researcher", "settings": {}},
        ]

        manager = ToolManager()
        result = await manager.discover_available_tools(
            agent_id=uuid4(),
            tools_config=tools_config,
            mcp_server_instance_service=mcp_service,
            agent_service=agent_service,
            base_url="",  # Empty
        )

        agent_tool_defs = [
            t for t in result if t.get("function", {}).get("name", "").startswith("delegate_to_")
        ]
        assert len(agent_tool_defs) == 0

    @pytest.mark.asyncio
    async def test_agent_tool_with_settings(self):
        """Agent tools should pass settings like a2a_url and description_override."""
        agent_service = AsyncMock()
        agent_service.get_by_name = AsyncMock(return_value=_make_mock_agent())
        mcp_service = AsyncMock()

        tools_config = [
            {
                "type": "agent",
                "name": "researcher",
                "settings": {
                    "a2a_url": "http://custom:9999/rpc",
                    "description_override": "Custom researcher",
                },
            },
        ]

        manager = ToolManager()
        result = await manager.discover_available_tools(
            agent_id=uuid4(),
            tools_config=tools_config,
            mcp_server_instance_service=mcp_service,
            agent_service=agent_service,
            base_url="http://localhost:8000/api/v1",
        )

        agent_tool_defs = [
            t for t in result if t.get("function", {}).get("name", "").startswith("delegate_to_")
        ]
        assert len(agent_tool_defs) == 1
        assert "Custom researcher" in agent_tool_defs[0]["function"]["description"]

    @pytest.mark.asyncio
    async def test_agent_tool_skipped_when_factory_returns_none(self):
        """When factory returns None (agent not found), no tool is added."""
        agent_service = AsyncMock()
        agent_service.get_by_name = AsyncMock(return_value=None)
        mcp_service = AsyncMock()

        tools_config = [
            {"type": "agent", "name": "nonexistent", "settings": {}},
        ]

        manager = ToolManager()
        result = await manager.discover_available_tools(
            agent_id=uuid4(),
            tools_config=tools_config,
            mcp_server_instance_service=mcp_service,
            agent_service=agent_service,
            base_url="http://localhost:8000/api/v1",
        )

        agent_tool_defs = [
            t for t in result if t.get("function", {}).get("name", "").startswith("delegate_to_")
        ]
        assert len(agent_tool_defs) == 0

    @pytest.mark.asyncio
    async def test_code_tools_still_work(self):
        """Existing code tool discovery should not be broken."""
        mcp_service = AsyncMock()

        tools_config = [
            {"type": "code", "name": "file_tools", "settings": {}},
        ]

        manager = ToolManager()
        result = await manager.discover_available_tools(
            agent_id=uuid4(),
            tools_config=tools_config,
            mcp_server_instance_service=mcp_service,
        )

        # Should have at least built-in tools; code tool may or may not resolve
        # depending on the code_tools_loader registry, but should not raise
        assert isinstance(result, list)
        assert len(result) >= 1  # At least completion tool

    @pytest.mark.asyncio
    async def test_mixed_tool_types(self):
        """Mixed code and agent tools should both be processed."""
        agent_service = AsyncMock()
        agent_service.get_by_name = AsyncMock(return_value=_make_mock_agent())
        mcp_service = AsyncMock()

        tools_config = [
            {"type": "code", "name": "file_tools", "settings": {}},
            {"type": "agent", "name": "researcher", "settings": {}},
        ]

        manager = ToolManager()
        result = await manager.discover_available_tools(
            agent_id=uuid4(),
            tools_config=tools_config,
            mcp_server_instance_service=mcp_service,
            agent_service=agent_service,
            base_url="http://localhost:8000/api/v1",
        )

        agent_tool_defs = [
            t for t in result if t.get("function", {}).get("name", "").startswith("delegate_to_")
        ]
        assert len(agent_tool_defs) == 1

    @pytest.mark.asyncio
    async def test_backward_compatible_no_new_params(self):
        """Calling without new params should work (backward compatible)."""
        mcp_service = AsyncMock()

        manager = ToolManager()
        result = await manager.discover_available_tools(
            agent_id=uuid4(),
            tools_config=None,
            mcp_server_instance_service=mcp_service,
        )

        # Should return built-in tools only
        assert isinstance(result, list)
        assert len(result) >= 1
