"""OpenAPIToolFactory.get_tool_definition_by_name — by-name schema lookup."""

from types import SimpleNamespace

from agentarea_agents_sdk.tools.openapi_tool import OpenAPIToolFactory


def _conn(*ops):
    return SimpleNamespace(available_tools=list(ops))


def test_returns_function_definition_for_known_name():
    op = {
        "name": "listCustomers",
        "description": "List Stripe customers.",
        "inputSchema": {
            "type": "object",
            "properties": {"limit": {"type": "integer"}},
            "required": [],
        },
    }
    result = OpenAPIToolFactory.get_tool_definition_by_name(_conn(op), "listCustomers")
    assert result is not None
    assert result["type"] == "function"
    assert result["function"]["name"] == "listCustomers"
    assert result["function"]["description"] == "List Stripe customers."
    assert result["function"]["parameters"]["properties"]["limit"]["type"] == "integer"


def test_returns_none_for_unknown_name():
    op = {"name": "listCustomers", "description": "x", "inputSchema": {"type": "object"}}
    assert (
        OpenAPIToolFactory.get_tool_definition_by_name(_conn(op), "createInvoice") is None
    )


def test_returns_none_when_connection_has_no_available_tools():
    conn = SimpleNamespace(available_tools=None)
    assert OpenAPIToolFactory.get_tool_definition_by_name(conn, "x") is None


def test_returns_none_when_connection_lacks_attribute():
    conn = SimpleNamespace()
    assert OpenAPIToolFactory.get_tool_definition_by_name(conn, "x") is None


def test_matches_slugified_name_too():
    """LLM-facing names are slugified; lookup must accept the slug back."""
    op = {
        "name": "List items / orders",
        "description": "Slashed and spaced operation name.",
        "inputSchema": {"type": "object"},
    }
    result = OpenAPIToolFactory.get_tool_definition_by_name(
        _conn(op), "List_items___orders"
    )
    assert result is not None
    assert result["function"]["name"] == "List_items___orders"


def test_falls_back_to_method_path_description_when_missing():
    op = {"name": "doStuff", "description": "", "inputSchema": {"type": "object"}}
    result = OpenAPIToolFactory.get_tool_definition_by_name(_conn(op), "doStuff")
    assert result is not None
    assert "doStuff" in result["function"]["description"]


def test_falls_back_to_empty_object_schema_when_input_schema_missing():
    op = {"name": "noParams", "description": "x"}
    result = OpenAPIToolFactory.get_tool_definition_by_name(_conn(op), "noParams")
    assert result is not None
    assert result["function"]["parameters"]["type"] == "object"
    assert "properties" in result["function"]["parameters"]


def test_skips_entries_with_blank_name():
    bad = {"name": "", "description": "x", "inputSchema": {}}
    good = {"name": "real", "description": "y", "inputSchema": {"type": "object"}}
    assert OpenAPIToolFactory.get_tool_definition_by_name(_conn(bad, good), "real") is not None
    assert OpenAPIToolFactory.get_tool_definition_by_name(_conn(bad), "") is None
