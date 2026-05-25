"""Unit tests for ToolProvider protocol and ToolCatalog."""

from agentarea_agents_sdk.tools.tool_catalog import ToolCatalog
from agentarea_agents_sdk.tools.tool_provider import (
    AgentToolProvider,
    BuiltinToolProvider,
    CodeToolProvider,
    MCPToolProvider,
    ToolProvider,
)


def _make_tool_def(name: str) -> dict:
    """Create a minimal OpenAI-format tool definition."""
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": f"Tool {name}",
            "parameters": {"type": "object", "properties": {}},
        },
    }


class TestToolProviderProtocol:
    def test_mcp_provider_implements_protocol(self):
        p = MCPToolProvider(name="github", instance_id="123", tools=[_make_tool_def("list_repos")])
        assert isinstance(p, ToolProvider)

    def test_code_provider_implements_protocol(self):
        p = CodeToolProvider(name="math", tools=[_make_tool_def("calculate")])
        assert isinstance(p, ToolProvider)

    def test_agent_provider_implements_protocol(self):
        p = AgentToolProvider(name="analyst", agent_id="456", tools=[_make_tool_def("analyze")])
        assert isinstance(p, ToolProvider)

    def test_builtin_provider_implements_protocol(self):
        p = BuiltinToolProvider(name="builtin", tools=[_make_tool_def("completion")])
        assert isinstance(p, ToolProvider)


class TestCatalogEntry:
    def test_mcp_catalog_entry(self):
        tools = [_make_tool_def("list_repos"), _make_tool_def("create_issue")]
        p = MCPToolProvider(name="github", instance_id="123", tools=tools)
        entry = p.get_catalog_entry()
        assert entry.name == "github"
        assert entry.provider_type == "mcp"
        assert entry.tool_names == ["list_repos", "create_issue"]

    def test_provider_type(self):
        assert MCPToolProvider(name="a", instance_id="", tools=[]).provider_type == "mcp"
        assert CodeToolProvider(name="a", tools=[]).provider_type == "code"
        assert AgentToolProvider(name="a", agent_id="", tools=[]).provider_type == "agent"
        assert BuiltinToolProvider(name="a", tools=[]).provider_type == "builtin"


class TestToolCatalog:
    def _make_catalog(self, activated=None):
        providers = [
            MCPToolProvider(
                name="github",
                instance_id="1",
                tools=[_make_tool_def("list_repos"), _make_tool_def("create_issue")],
            ),
            MCPToolProvider(
                name="jira",
                instance_id="2",
                tools=[_make_tool_def("get_ticket"), _make_tool_def("create_ticket")],
            ),
            CodeToolProvider(
                name="math",
                tools=[_make_tool_def("calculate")],
            ),
            BuiltinToolProvider(
                name="builtin",
                tools=[_make_tool_def("completion")],
            ),
        ]
        return ToolCatalog(providers, activated=activated)

    def test_build_prompt_text_lists_all_sources(self):
        catalog = self._make_catalog()
        text = catalog.build_prompt_text()
        assert "github" in text
        assert "jira" in text
        assert "math" in text
        assert "builtin" in text
        assert "activate_tool_source" in text

    def test_build_prompt_text_excludes_activated(self):
        catalog = self._make_catalog(activated={"github"})
        text = catalog.build_prompt_text()
        assert "github" not in text
        assert "jira" in text

    def test_build_prompt_text_empty_when_all_activated(self):
        catalog = self._make_catalog(activated={"github", "jira", "math", "builtin"})
        text = catalog.build_prompt_text()
        assert text == ""

    def test_build_prompt_text_shows_tool_count(self):
        catalog = self._make_catalog()
        text = catalog.build_prompt_text()
        assert "(2 tools)" in text  # github has 2 tools
        assert "(1 tools)" in text  # math has 1 tool

    def test_activate_returns_tool_definitions(self):
        catalog = self._make_catalog()
        tools = catalog.activate("github")
        assert len(tools) == 2
        names = [t["function"]["name"] for t in tools]
        assert "list_repos" in names
        assert "create_issue" in names

    def test_activate_marks_as_activated(self):
        catalog = self._make_catalog()
        catalog.activate("github")
        assert "github" in catalog.activated_sources

    def test_activate_unknown_returns_empty(self):
        catalog = self._make_catalog()
        tools = catalog.activate("nonexistent")
        assert tools == []

    def test_activate_is_idempotent(self):
        catalog = self._make_catalog()
        tools1 = catalog.activate("github")
        tools2 = catalog.activate("github")
        assert tools1 == tools2

    def test_get_activated_tool_definitions(self):
        catalog = self._make_catalog()
        catalog.activate("github")
        catalog.activate("math")
        all_tools = catalog.get_activated_tool_definitions()
        names = [t["function"]["name"] for t in all_tools]
        assert "list_repos" in names
        assert "calculate" in names
        assert "get_ticket" not in names

    def test_get_activate_tool_source_definition(self):
        catalog = self._make_catalog()
        tool_def = catalog.get_activate_tool_source_definition()
        assert tool_def["function"]["name"] == "activate_tool_source"
        params = tool_def["function"]["parameters"]
        assert "source_name" in params["properties"]
        enum = params["properties"]["source_name"].get("enum")
        assert enum is not None
        assert "github" in enum

    def test_activate_tool_source_enum_shrinks(self):
        catalog = self._make_catalog()
        catalog.activate("github")
        tool_def = catalog.get_activate_tool_source_definition()
        enum = tool_def["function"]["parameters"]["properties"]["source_name"]["enum"]
        assert "github" not in enum
        assert "jira" in enum

    def test_provider_names(self):
        catalog = self._make_catalog()
        names = catalog.provider_names
        assert set(names) == {"github", "jira", "math", "builtin"}

    def test_empty_catalog(self):
        catalog = ToolCatalog([])
        assert catalog.build_prompt_text() == ""
        assert catalog.activate("anything") == []
        assert catalog.get_activated_tool_definitions() == []
