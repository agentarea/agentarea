"""The MCP agent tools set an agent's tools the way the REST routes do.

``agents_update`` had no ``tools`` argument, so a connection provisioned over
MCP could never be attached to an agent that already existed. Both tools now
refuse a code tool that names no registered toolset, as REST does.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import agentarea_common.auth.permission as permission
import pytest
from agentarea_agents_sdk.mcp_server.auth import use_mcp_user_context
from agentarea_agents_sdk.tools.base_tool import ToolError
from agentarea_api.tools import agents_toolset
from agentarea_api.tools.agents_toolset import AgentsToolset
from agentarea_common.auth.context import UserContext

CALLER = UserContext(user_id="user-a", workspace_id="ws-a")
MCP_TOOL = {"type": "mcp", "name": "github"}


@pytest.fixture
def service(monkeypatch):
    @asynccontextmanager
    async def _ctx():
        yield AsyncMock(), CALLER, MagicMock(), AsyncMock(), AsyncMock()

    agent = SimpleNamespace(id=uuid4(), name="Ops")
    service = MagicMock(
        create_agent=AsyncMock(return_value=agent), update_agent=AsyncMock(return_value=agent)
    )
    monkeypatch.setattr(agents_toolset, "platform_context", _ctx)
    monkeypatch.setattr(agents_toolset, "_build_service", lambda *_: service)
    monkeypatch.setattr(permission, "require_permission", AsyncMock())
    with use_mcp_user_context(CALLER):
        yield service


@pytest.mark.asyncio
async def test_update_replaces_the_agents_tools(service):
    tools = [{"type": "code", "name": "agentarea/shell"}, MCP_TOOL]

    result = json.loads(await AgentsToolset().update(str(uuid4()), tools=tools))

    assert "error" not in result
    payload = service.update_agent.await_args.args[1]
    assert [tool.type for tool in payload.tools] == ["code", "mcp"]
    assert payload.model_dump(exclude_unset=True).keys() == {"tools"}


@pytest.mark.asyncio
async def test_update_without_tools_leaves_them_alone(service):
    await AgentsToolset().update(str(uuid4()), name="Ops")

    assert "tools" not in service.update_agent.await_args.args[1].model_dump(exclude_unset=True)


@pytest.mark.asyncio
async def test_update_refuses_a_code_tool_no_toolset_provides(service):
    tools = [{"type": "code", "name": "agentarea/not-a-toolset"}]

    with pytest.raises(ToolError, match="agentarea/not-a-toolset"):
        await AgentsToolset().update(str(uuid4()), tools=tools)

    service.update_agent.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_refuses_a_code_tool_no_toolset_provides(service):
    with pytest.raises(ToolError, match="agentarea/not-a-toolset"):
        await AgentsToolset().create(
            name="Ops",
            model_id=str(uuid4()),
            tools=[{"type": "code", "name": "agentarea/not-a-toolset"}],
        )

    service.create_agent.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_passes_the_reasoning_effort(service):
    await AgentsToolset().create(
        name="Ops", model_id=str(uuid4()), tools=[], reasoning_effort="medium"
    )

    assert service.create_agent.await_args.args[0].reasoning_effort == "medium"


@pytest.mark.asyncio
async def test_update_sets_or_clears_the_reasoning_effort_and_omitting_it_keeps_it(service):
    await AgentsToolset().update(str(uuid4()), reasoning_effort="high")
    assert service.update_agent.await_args.args[1].model_dump(exclude_unset=True) == {
        "reasoning_effort": "high"
    }

    await AgentsToolset().update(str(uuid4()), reasoning_effort="")
    assert service.update_agent.await_args.args[1].model_dump(exclude_unset=True) == {
        "reasoning_effort": None
    }

    await AgentsToolset().update(str(uuid4()), name="Ops")
    assert "reasoning_effort" not in service.update_agent.await_args.args[1].model_dump(
        exclude_unset=True
    )


@pytest.mark.asyncio
async def test_get_returns_the_reasoning_effort(monkeypatch):
    @asynccontextmanager
    async def _read_ctx():
        yield AsyncMock(), CALLER, MagicMock(), AsyncMock(), AsyncMock()

    agent = SimpleNamespace(
        id=uuid4(),
        name="Ops",
        description=None,
        model_id=None,
        instruction=None,
        agent_type="stateless",
        reasoning_effort="low",
    )
    service = MagicMock(get=AsyncMock(return_value=agent))
    monkeypatch.setattr(agents_toolset, "platform_read_context", _read_ctx)
    monkeypatch.setattr(agents_toolset, "_build_service", lambda *_: service)
    monkeypatch.setattr(permission, "require_permission", AsyncMock())

    with use_mcp_user_context(CALLER):
        result = json.loads(await AgentsToolset().get(str(agent.id)))

    assert result["reasoning_effort"] == "low"
