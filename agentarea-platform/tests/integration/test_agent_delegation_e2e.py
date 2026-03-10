"""Integration test for agent-to-agent delegation flow."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from agentarea_agents_sdk.tools.tool_manager import ToolManager


class TestAgentDelegationE2E:
    @pytest.mark.asyncio
    async def test_full_discovery_with_agent_tool(self):
        """ToolManager discovers agent tools and produces valid OpenAI schema."""
        mock_agent_service = AsyncMock()
        target = MagicMock()
        target.id = uuid4()
        target.name = "summarizer"
        target.description = "Summarizes long documents"
        mock_agent_service.get_by_name.return_value = target

        tools_config = [
            {"type": "agent", "name": "summarizer"},
        ]

        manager = ToolManager()
        tools = await manager.discover_available_tools(
            agent_id=uuid4(),
            tools_config=tools_config,
            mcp_server_instance_service=AsyncMock(),
            agent_service=mock_agent_service,
            base_url="http://api:8000/api/v1",
        )

        # Should have built-in tools (completion) + the agent tool
        names = [t.get("function", {}).get("name", "") for t in tools]
        assert "delegate_to_summarizer" in names

        # Verify schema is valid OpenAI format
        agent_tool = next(
            t for t in tools if "delegate_to_" in t.get("function", {}).get("name", "")
        )
        assert agent_tool["type"] == "function"
        assert "parameters" in agent_tool["function"]
        assert "message" in agent_tool["function"]["parameters"]["properties"]
        assert "message" in agent_tool["function"]["parameters"]["required"]

    @pytest.mark.asyncio
    async def test_mixed_tool_types_discovery(self):
        """ToolManager discovers code + agent tools together."""
        mock_agent_service = AsyncMock()
        target = MagicMock()
        target.id = uuid4()
        target.name = "researcher"
        target.description = "Researches topics"
        mock_agent_service.get_by_name.return_value = target

        tools_config = [
            {"type": "code", "name": "web_search"},
            {"type": "agent", "name": "researcher"},
            {"type": "mcp", "name": "nonexistent-mcp"},
        ]

        manager = ToolManager()
        tools = await manager.discover_available_tools(
            agent_id=uuid4(),
            tools_config=tools_config,
            mcp_server_instance_service=AsyncMock(),
            agent_service=mock_agent_service,
            base_url="http://api:8000/api/v1",
        )

        names = [t.get("function", {}).get("name", "") for t in tools]
        assert "delegate_to_researcher" in names

    @pytest.mark.asyncio
    async def test_agent_tool_not_found_graceful(self):
        """Missing agent should not break discovery of other tools."""
        mock_agent_service = AsyncMock()
        mock_agent_service.get_by_name.return_value = None

        tools_config = [
            {"type": "agent", "name": "nonexistent-agent"},
        ]

        manager = ToolManager()
        tools = await manager.discover_available_tools(
            agent_id=uuid4(),
            tools_config=tools_config,
            mcp_server_instance_service=AsyncMock(),
            agent_service=mock_agent_service,
            base_url="http://api:8000/api/v1",
        )

        # Should still have built-in tools, but no agent tool
        agent_tools = [
            t for t in tools if "delegate_to_" in t.get("function", {}).get("name", "")
        ]
        assert len(agent_tools) == 0

    @pytest.mark.asyncio
    async def test_backward_compat_without_agent_service(self):
        """Calling without agent_service should still work (backward compat)."""
        tools_config = [
            {"type": "agent", "name": "some-agent"},
        ]

        manager = ToolManager()
        # No agent_service or base_url — should skip agent tools gracefully
        tools = await manager.discover_available_tools(
            agent_id=uuid4(),
            tools_config=tools_config,
            mcp_server_instance_service=AsyncMock(),
        )

        agent_tools = [
            t for t in tools if "delegate_to_" in t.get("function", {}).get("name", "")
        ]
        assert len(agent_tools) == 0
