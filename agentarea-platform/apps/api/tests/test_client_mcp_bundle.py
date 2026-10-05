"""A client's endpoint serves its platform toolsets beside its MCP instances.

Platform tools run as the caller in the client's workspace, and only the ones
the client carries are listed or reachable.
"""

from typing import cast
from unittest.mock import AsyncMock

import pytest
from agentarea_agents_sdk.mcp_server import create_mcp_server
from agentarea_agents_sdk.mcp_server.auth import get_mcp_user_context
from agentarea_agents_sdk.tools.decorator_tool import Toolset, tool_method
from agentarea_agents_sdk.tools.tool_definition import ToolsetMetadata
from agentarea_api.api.v1 import client_mcp
from agentarea_common.auth.context import UserContext, UserPrincipal
from agentarea_mcp.application.mcp_aggregator import AggregatedMember, MCPAggregatorProxy
from agentarea_mcp.domain.client_models import ClientPlatformToolset
from mcp.types import CallToolRequestParams, TextContent

CLIENT_ID = "22222222-2222-2222-2222-222222222222"


class _ProbeToolset(Toolset):
    # Metadata without @toolset: registering would leak into the global catalog.
    __toolset_meta__ = ToolsetMetadata(namespace="test/probe")

    @tool_method
    async def whereami(self) -> str:
        """Name the workspace the call runs in."""
        return get_mcp_user_context().workspace_id

    @tool_method
    async def wipe(self) -> str:
        """Destroy everything."""
        return "wiped"


class _Proxy:
    def __init__(self) -> None:
        self.instance_names: dict[str, str] = {}

    async def list_namespaced_tools(self):
        return [{"name": "gh__create_issue", "description": "", "inputSchema": {"type": "object"}}]

    def owner_of(self, name):
        if name == "gh__create_issue":
            return AggregatedMember(mcp_instance_id="gh"), "create_issue"
        return None

    async def call_namespaced_tool(self, name, arguments):
        raise ValueError(f"No member owns tool {name}")


@pytest.fixture(autouse=True)
def platform(monkeypatch):
    server = create_mcp_server(toolsets=[_ProbeToolset()], name="t", workspace_argument=False)
    monkeypatch.setattr(client_mcp, "client_platform_server", lambda: server)
    return server


@pytest.fixture
def bundle(monkeypatch):
    """A client carrying ``probe`` without ``wipe``, entered by an outside caller."""
    scope = client_mcp.ClientScope(
        proxy=cast(MCPAggregatorProxy, _Proxy()),
        skill_registry={},
        platform_tools=client_mcp._platform_tools(
            CLIENT_ID, [ClientPlatformToolset(toolset="test/probe", disabled_methods=["wipe"])]
        ),
        user_context=UserContext(user_id="user-1", workspace_id="client-ws"),
        tool_policy={},
        actor_type="user",
    )

    async def resolve(_client_id):
        return scope

    monkeypatch.setattr(client_mcp, "_resolve_client_scope", resolve)
    monkeypatch.setattr(client_mcp, "_audit_tool_call", AsyncMock())
    token = client_mcp._client_id_var.set(CLIENT_ID)
    caller = UserPrincipal(user_id="user-1", accessible_workspaces=["client-ws", "other-ws"])
    with client_mcp.use_mcp_user_context(caller):
        yield
    client_mcp._client_id_var.reset(token)


def test_selection_drops_disabled_methods_and_toolsets_no_longer_served():
    attached = [
        ClientPlatformToolset(toolset="test/probe", disabled_methods=["wipe", "renamed_away"]),
        ClientPlatformToolset(toolset="test/retired", disabled_methods=None),
    ]

    assert client_mcp._platform_tools(CLIENT_ID, attached) == frozenset({"probe_whereami"})


@pytest.mark.asyncio
async def test_lists_the_carried_platform_tools_beside_instance_tools(bundle):
    listed = await client_mcp._list_tools(None, None)

    assert {tool.name for tool in listed.tools} == {"probe_whereami", "gh__create_issue"}


@pytest.mark.asyncio
async def test_a_platform_tool_runs_in_the_clients_workspace(bundle):
    result = await client_mcp._call_tool(
        None, CallToolRequestParams(name="probe_whereami", arguments={})
    )

    assert not result.is_error
    assert result.content == [TextContent(type="text", text="client-ws")]


@pytest.mark.asyncio
async def test_a_disabled_platform_method_is_not_reachable(bundle):
    with pytest.raises(ValueError, match="No member owns tool probe_wipe"):
        await client_mcp._call_tool(None, CallToolRequestParams(name="probe_wipe", arguments={}))
