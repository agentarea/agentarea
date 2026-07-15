"""Tests for MCP tool serialization — the single normalizer every discovery
path uses to turn an mcp.types.Tool into the plain dict we persist."""

from types import SimpleNamespace

from agentarea_mcp.tool_serialization import serialize_mcp_tool


def _tool(**kwargs):
    """A duck-typed stand-in for mcp.types.Tool (only the attrs we read)."""
    kwargs.setdefault("name", "do_thing")
    kwargs.setdefault("description", "does a thing")
    kwargs.setdefault("inputSchema", {"type": "object"})
    kwargs.setdefault("title", None)
    kwargs.setdefault("annotations", None)
    return SimpleNamespace(**kwargs)


class TestSerializeMcpTool:
    def test_captures_core_fields(self):
        out = serialize_mcp_tool(_tool())
        assert out["name"] == "do_thing"
        assert out["description"] == "does a thing"
        assert out["inputSchema"] == {"type": "object"}

    def test_missing_description_and_schema_default_to_empty(self):
        out = serialize_mcp_tool(_tool(description=None, inputSchema=None))
        assert out["description"] == ""
        assert out["inputSchema"] == {}

    def test_no_annotations_key_when_server_provides_none(self):
        out = serialize_mcp_tool(_tool(annotations=None))
        assert "annotations" not in out
        assert "title" not in out

    def test_captures_title(self):
        out = serialize_mcp_tool(_tool(title="Do Thing"))
        assert out["title"] == "Do Thing"

    def test_captures_annotations_from_pydantic_like_model(self):
        ann = SimpleNamespace(
            model_dump=lambda exclude_none: {
                "readOnlyHint": True,
                "destructiveHint": False,
                "openWorldHint": True,
            }
        )
        out = serialize_mcp_tool(_tool(annotations=ann))
        assert out["annotations"] == {
            "readOnlyHint": True,
            "destructiveHint": False,
            "openWorldHint": True,
        }

    def test_captures_annotations_from_dict(self):
        out = serialize_mcp_tool(
            _tool(annotations={"readOnlyHint": True, "idempotentHint": None})
        )
        # None hints are dropped so the blob only carries what the server set.
        assert out["annotations"] == {"readOnlyHint": True}

    def test_empty_annotations_omitted(self):
        out = serialize_mcp_tool(_tool(annotations={"readOnlyHint": None}))
        assert "annotations" not in out

    def test_result_is_json_serializable(self):
        import json

        ann = SimpleNamespace(model_dump=lambda exclude_none: {"readOnlyHint": True})
        out = serialize_mcp_tool(_tool(title="T", annotations=ann))
        json.dumps(out)  # must not raise
