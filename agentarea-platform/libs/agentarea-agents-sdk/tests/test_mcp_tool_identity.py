"""MCP tools reach the model under a name that identifies their server.

Two attached servers may advertise the same raw tool name. The model-facing
name must tell them apart, and the identity behind it must route the call to
the right instance with the raw name the server advertised.
"""

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from agentarea_agents_sdk.tools.mcp_tool_identity import (
    MAX_TOOL_NAME_LENGTH,
    McpToolIdentity,
    qualify_mcp_tool_name,
)
from agentarea_agents_sdk.tools.tool_manager import ToolManager


def _instance(name: str, tools: list[str]) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        name=name,
        tools=[{"name": t, "description": f"{t} tool", "inputSchema": {}} for t in tools],
        json_spec={},
        verification={"status": "succeeded"},
        status=None,
    )


class _FakeMcpService:
    def __init__(self, *instances: SimpleNamespace) -> None:
        self._by_id = {i.id: i for i in instances}
        self.calls: list[tuple[UUID, str, dict]] = []

    async def get(self, instance_id: UUID):
        return self._by_id.get(instance_id)

    async def get_by_name(self, name: str):
        return next((i for i in self._by_id.values() if i.name == name), None)

    async def execute_tool(self, instance_id, tool_name, tool_args, **_):
        self.calls.append((instance_id, tool_name, tool_args))
        return {"success": True, "result": "ok"}


def _attach(instance: SimpleNamespace, allowed=None, *, omit_allowed: bool = False) -> dict:
    settings = {} if omit_allowed else {"allowed_tools": allowed}
    return {"type": "mcp", "name": str(instance.id), "settings": settings}


def _names(defs: list[dict]) -> list[str]:
    return [d["function"]["name"] for d in defs]


class TestQualifyName:
    def test_prefixes_server_label(self):
        assert qualify_mcp_tool_name("github", "search") == "mcp__github__search"

    def test_sanitizes_characters_models_reject(self):
        assert qualify_mcp_tool_name("My GitHub!", "list.repos") == "mcp__my_github___list_repos"

    def test_long_names_are_shortened_deterministically(self):
        raw = "x" * 100
        name = qualify_mcp_tool_name("server", raw)
        assert len(name) <= MAX_TOOL_NAME_LENGTH
        assert name == qualify_mcp_tool_name("server", raw)
        assert name != qualify_mcp_tool_name("server", raw + "y")


class TestIdentity:
    def test_canonical_id_is_instance_and_raw_name(self):
        instance_id = str(uuid4())
        identity = McpToolIdentity("mcp__github__search", instance_id, "search", instance_id)
        assert identity.canonical == f"mcp:{instance_id}:search"
        assert identity.policy_names == (identity.canonical, "search")

    def test_attachment_by_name_is_also_a_policy_name(self):
        instance_id = str(uuid4())
        identity = McpToolIdentity("mcp__github__search", instance_id, "search", "github")
        assert identity.policy_names == (f"mcp:{instance_id}:search", "mcp:github:search", "search")


class TestDiscovery:
    @pytest.mark.asyncio
    async def test_same_tool_on_two_servers_gets_two_names(self):
        work = _instance("github", ["search"])
        personal = _instance("github", ["search"])
        service = _FakeMcpService(work, personal)

        result = await ToolManager().discover_available_tools_split(
            agent_id=uuid4(),
            tools_config=[_attach(work), _attach(personal)],
            mcp_server_instance_service=service,
        )

        mcp_names = [n for n in _names(result.explicit_tools) if n.startswith("mcp__")]
        assert len(mcp_names) == 2
        assert len(set(mcp_names)) == 2
        routed = {result.tool_identities[n].instance_id for n in mcp_names}
        assert routed == {str(work.id), str(personal.id)}
        assert {result.tool_identities[n].raw_name for n in mcp_names} == {"search"}

    @pytest.mark.asyncio
    async def test_empty_allowlist_exposes_no_tools(self):
        server = _instance("github", ["search", "create_issue"])
        result = await ToolManager().discover_available_tools_split(
            agent_id=uuid4(),
            tools_config=[_attach(server, [])],
            mcp_server_instance_service=_FakeMcpService(server),
        )
        assert not [n for n in _names(result.explicit_tools) if n.startswith("mcp__")]
        assert result.tool_identities == {}

    @pytest.mark.asyncio
    async def test_absent_allowlist_exposes_every_tool(self):
        server = _instance("github", ["search", "create_issue"])
        for attachment in (_attach(server, None), _attach(server, omit_allowed=True)):
            result = await ToolManager().discover_available_tools_split(
                agent_id=uuid4(),
                tools_config=[attachment],
                mcp_server_instance_service=_FakeMcpService(server),
            )
            assert set(result.tool_identities) == {
                "mcp__github__search",
                "mcp__github__create_issue",
            }

    @pytest.mark.asyncio
    async def test_allowlist_keeps_only_listed_tools(self):
        server = _instance("github", ["search", "create_issue"])
        result = await ToolManager().discover_available_tools_split(
            agent_id=uuid4(),
            tools_config=[_attach(server, [{"tool_name": "search"}])],
            mcp_server_instance_service=_FakeMcpService(server),
        )
        assert set(result.tool_identities) == {"mcp__github__search"}

    @pytest.mark.asyncio
    async def test_providers_carry_the_same_identities(self):
        server = _instance("github", ["search"])
        discovery = await ToolManager().discover_tool_providers(
            agent_id=uuid4(),
            tools_config=[_attach(server)],
            mcp_server_instance_service=_FakeMcpService(server),
        )
        mcp = [p for p in discovery.providers if p.provider_type == "mcp"]
        assert _names(mcp[0].get_tool_definitions()) == ["mcp__github__search"]
        assert discovery.tool_identities["mcp__github__search"].instance_id == str(server.id)


class TestExecution:
    @pytest.mark.asyncio
    async def test_call_reaches_server_under_its_raw_name(self):
        from agentarea_agents_sdk.tools.mcp_tool import MCPToolFactory

        server = _instance("github", ["search"])
        service = _FakeMcpService(server)
        (tool,) = await MCPToolFactory.create_tools_from_server(server.id, service)
        tool.expose_as("mcp__github__search")

        await tool.execute(q="agentarea")

        assert tool.name == "mcp__github__search"
        assert service.calls == [(server.id, "search", {"q": "agentarea"})]
