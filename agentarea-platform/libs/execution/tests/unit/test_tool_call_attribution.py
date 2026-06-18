"""Tests for tool-call MCP/server attribution on ToolCall events.

Covers:
- MCPToolResult accepts and serializes the new attribution fields.
- _server_icon_from_instance returns the first icon src and guards
  missing/empty/None json_spec.
"""

from types import SimpleNamespace

import pytest


class TestMCPToolResultAttributionFields:
    """MCPToolResult exposes source/server_* attribution fields."""

    def test_defaults_are_none(self):
        from agentarea_execution.models import MCPToolResult

        result = MCPToolResult(success=True, result="ok")
        assert result.source is None
        assert result.server_instance_id is None
        assert result.server_name is None
        assert result.server_icon is None

    def test_accepts_and_serializes_attribution(self):
        from agentarea_execution.models import MCPToolResult

        result = MCPToolResult(
            success=True,
            result="ok",
            source="mcp",
            server_instance_id="11111111-1111-1111-1111-111111111111",
            server_name="GitHub",
            server_icon="https://example.com/icon.png",
        )

        dumped = result.model_dump()
        assert dumped["source"] == "mcp"
        assert dumped["server_instance_id"] == "11111111-1111-1111-1111-111111111111"
        assert dumped["server_name"] == "GitHub"
        assert dumped["server_icon"] == "https://example.com/icon.png"


class TestServerIconFromInstance:
    """_server_icon_from_instance extracts the first icon src, else None."""

    def test_returns_first_icon_src(self):
        from agentarea_execution.activities.agent_execution_activities import (
            _server_icon_from_instance,
        )

        instance = SimpleNamespace(
            json_spec={"icons": [{"src": "https://example.com/icon.png"}]}
        )
        assert (
            _server_icon_from_instance(instance) == "https://example.com/icon.png"
        )

    def test_returns_first_when_multiple_icons(self):
        from agentarea_execution.activities.agent_execution_activities import (
            _server_icon_from_instance,
        )

        instance = SimpleNamespace(
            json_spec={
                "icons": [
                    {"src": "https://example.com/first.png"},
                    {"src": "https://example.com/second.png"},
                ]
            }
        )
        assert _server_icon_from_instance(instance) == "https://example.com/first.png"

    @pytest.mark.parametrize(
        "json_spec",
        [
            None,
            {},
            {"icons": None},
            {"icons": []},
            {"icons": "not-a-list"},
            {"icons": [{}]},
            {"icons": [{"src": None}]},
            {"icons": [{"src": 123}]},
            {"icons": ["not-a-dict"]},
        ],
    )
    def test_returns_none_for_missing_or_invalid(self, json_spec):
        from agentarea_execution.activities.agent_execution_activities import (
            _server_icon_from_instance,
        )

        instance = SimpleNamespace(json_spec=json_spec)
        assert _server_icon_from_instance(instance) is None

    def test_guards_instance_without_json_spec_attr(self):
        from agentarea_execution.activities.agent_execution_activities import (
            _server_icon_from_instance,
        )

        instance = SimpleNamespace()
        assert _server_icon_from_instance(instance) is None
