"""Tests for AgentToolFactory."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from uuid import UUID

import httpx
import pytest

from agentarea_agents_sdk.tools.a2a_agent_tool import A2AAgentTool
from agentarea_agents_sdk.tools.agent_tool_factory import AgentToolFactory
from agentarea_agents_sdk.tools.delegation_tool import DelegationTool

AGENT_ID = "6f0c3e2a-1b2c-4d5e-8f90-123456789abc"


def _make_mock_agent(agent_id="agent-123", name="researcher", description="Researches topics"):
    return SimpleNamespace(id=agent_id, name=name, description=description)


class TestAgentToolFactoryCreateTool:
    """Tests for AgentToolFactory.create_tool()."""

    @pytest.mark.asyncio
    async def test_create_tool_resolves_agent(self):
        agent_service = AsyncMock()
        agent_service.get = AsyncMock(return_value=_make_mock_agent())

        tool = await AgentToolFactory.create_tool(
            agent_name="researcher",
            agent_id=AGENT_ID,
            agent_service=agent_service,
            base_url="http://localhost:8000",
        )

        assert tool is not None
        # Single facade tool; transport binding is A2A here (no task_service provided).
        assert isinstance(tool, DelegationTool)
        assert tool.binding_kind == "a2a"
        assert isinstance(tool.binding, A2AAgentTool)
        assert tool.name == "delegate_to_researcher"
        assert "Researches topics" in tool.description
        agent_service.get.assert_awaited_once_with(UUID(AGENT_ID))

    @pytest.mark.asyncio
    async def test_create_tool_uses_default_url(self):
        agent_service = AsyncMock()
        agent_service.get = AsyncMock(return_value=_make_mock_agent())

        tool = await AgentToolFactory.create_tool(
            agent_name="researcher",
            agent_id=AGENT_ID,
            agent_service=agent_service,
            base_url="http://localhost:8000",
        )

        assert tool is not None
        assert tool.binding._a2a_url == "http://localhost:8000/agents/agent-123"

    @pytest.mark.asyncio
    async def test_create_tool_with_url_override(self):
        agent_service = AsyncMock()
        agent_service.get = AsyncMock(return_value=_make_mock_agent())

        tool = await AgentToolFactory.create_tool(
            agent_name="researcher",
            agent_id=AGENT_ID,
            agent_service=agent_service,
            base_url="http://localhost:8000",
            a2a_url_override="http://custom:9999/rpc",
        )

        assert tool is not None
        assert tool.binding_kind == "a2a"
        assert tool.binding._a2a_url == "http://custom:9999/rpc"

    @pytest.mark.asyncio
    async def test_create_tool_with_description_override(self):
        agent_service = AsyncMock()
        agent_service.get = AsyncMock(return_value=_make_mock_agent())

        tool = await AgentToolFactory.create_tool(
            agent_name="researcher",
            agent_id=AGENT_ID,
            agent_service=agent_service,
            base_url="http://localhost:8000",
            description_override="Custom description",
        )

        assert tool is not None
        assert "Custom description" in tool.description

    @pytest.mark.asyncio
    async def test_create_tool_returns_none_for_missing_agent(self):
        agent_service = AsyncMock()
        agent_service.get = AsyncMock(return_value=None)

        tool = await AgentToolFactory.create_tool(
            agent_name="nonexistent",
            agent_id=AGENT_ID,
            agent_service=agent_service,
            base_url="http://localhost:8000",
        )

        assert tool is None

    @pytest.mark.asyncio
    async def test_a_local_delegate_without_an_agent_id_is_not_resolved_by_name(self):
        # Names are not unique: resolving one would reach whichever agent last
        # took it. A delegate saved before ids were stored is not offered.
        agent_service = AsyncMock()
        agent_service.get_by_name = AsyncMock(return_value=_make_mock_agent())

        tool = await AgentToolFactory.create_tool(
            agent_name="researcher",
            agent_service=agent_service,
            base_url="http://localhost:8000",
        )

        assert tool is None
        agent_service.get_by_name.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_an_archived_agent_is_not_delegated_to(self):
        agent_service = AsyncMock()
        archived = _make_mock_agent()
        archived.status = "archived"
        agent_service.get = AsyncMock(return_value=archived)

        tool = await AgentToolFactory.create_tool(
            agent_name="researcher",
            agent_id=AGENT_ID,
            agent_service=agent_service,
            base_url="http://localhost:8000",
        )

        assert tool is None

    @pytest.mark.asyncio
    async def test_create_tool_returns_none_on_exception(self):
        agent_service = AsyncMock()
        agent_service.get = AsyncMock(side_effect=Exception("DB error"))

        tool = await AgentToolFactory.create_tool(
            agent_name="researcher",
            agent_id=AGENT_ID,
            agent_service=agent_service,
            base_url="http://localhost:8000",
        )

        assert tool is None

    @pytest.mark.asyncio
    async def test_create_tool_with_auth_token(self):
        agent_service = AsyncMock()
        agent_service.get = AsyncMock(return_value=_make_mock_agent())

        tool = await AgentToolFactory.create_tool(
            agent_name="researcher",
            agent_id=AGENT_ID,
            agent_service=agent_service,
            base_url="http://localhost:8000",
            auth_token="secret-token",
        )

        assert tool is not None
        assert tool.binding._auth_token == "secret-token"

    @pytest.mark.asyncio
    async def test_remote_agent_needs_no_local_agent(self):
        agent_service = AsyncMock()
        agent_service.get = AsyncMock(return_value=None)

        tool = await AgentToolFactory.create_tool(
            agent_name="aadocs-writer",
            agent_service=agent_service,
            base_url="http://localhost:8000",
            a2a_url_override="https://x.a2a.example.com",
            description_override="Writes the docs",
        )

        assert tool is not None
        assert tool.binding_kind == "a2a"
        assert tool.name == "delegate_to_aadocs_writer"
        assert tool.binding._a2a_url == "https://x.a2a.example.com"
        assert "Writes the docs" in tool.description
        agent_service.get.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_remote_agent_gets_the_token_provider_and_transport(self):
        async def token() -> str:
            return "t"

        transport = httpx.MockTransport(lambda request: httpx.Response(200))

        tool = await AgentToolFactory.create_tool(
            agent_name="aadocs-writer",
            agent_service=AsyncMock(),
            base_url="http://localhost:8000",
            a2a_url_override="https://example.com/rpc",
            auth_token_provider=token,
            http_transport=transport,
        )

        assert tool is not None
        assert tool.binding._auth_token_provider is token
        assert tool.binding._http_transport is transport


class TestAgentToolFactoryCreateToolsFromConfig:
    """Tests for AgentToolFactory.create_tools_from_config()."""

    @pytest.mark.asyncio
    async def test_filters_agent_type_only(self):
        agent_service = AsyncMock()
        agent_service.get = AsyncMock(return_value=_make_mock_agent())

        configs = [
            {"type": "code", "name": "file_reader"},
            {"type": "mcp", "name": "github"},
            {"type": "agent", "name": "researcher", "settings": {"agent_id": AGENT_ID}},
        ]

        tools = await AgentToolFactory.create_tools_from_config(
            tools_config=configs,
            agent_service=agent_service,
            base_url="http://localhost:8000",
        )

        assert len(tools) == 1
        assert tools[0].name == "delegate_to_researcher"
        agent_service.get.assert_awaited_once_with(UUID(AGENT_ID))

    @pytest.mark.asyncio
    async def test_skips_config_without_name(self):
        agent_service = AsyncMock()

        configs = [{"type": "agent"}]

        tools = await AgentToolFactory.create_tools_from_config(
            tools_config=configs,
            agent_service=agent_service,
            base_url="http://localhost:8000",
        )

        assert len(tools) == 0
        agent_service.get.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_passes_settings_to_create_tool(self):
        agent_service = AsyncMock()
        agent_service.get = AsyncMock(return_value=_make_mock_agent())

        configs = [
            {
                "type": "agent",
                "name": "researcher",
                "settings": {
                    "a2a_url": "http://custom/rpc",
                    "description_override": "Custom desc",
                },
            }
        ]

        tools = await AgentToolFactory.create_tools_from_config(
            tools_config=configs,
            agent_service=agent_service,
            base_url="http://localhost:8000",
        )

        assert len(tools) == 1
        assert tools[0].binding._a2a_url == "http://custom/rpc"
        assert "Custom desc" in tools[0].description

    @pytest.mark.asyncio
    async def test_skips_failed_tools(self):
        agent_service = AsyncMock()
        agent_service.get = AsyncMock(return_value=None)

        configs = [{"type": "agent", "name": "missing_agent"}]

        tools = await AgentToolFactory.create_tools_from_config(
            tools_config=configs,
            agent_service=agent_service,
            base_url="http://localhost:8000",
        )

        assert len(tools) == 0

    @pytest.mark.asyncio
    async def test_empty_config_list(self):
        agent_service = AsyncMock()

        tools = await AgentToolFactory.create_tools_from_config(
            tools_config=[],
            agent_service=agent_service,
            base_url="http://localhost:8000",
        )

        assert tools == []
