"""Tests for MCP Apps tool metadata visibility helpers."""

from agentarea_agents_sdk.tools.mcp_app_ui import (
    is_callable_from_app,
    is_visible_to_model,
    tool_ui_resource_uri,
    tool_visibility,
)


def test_missing_visibility_defaults_to_model_and_app():
    tool = {"name": "show", "_meta": {"ui": {"resourceUri": "ui://show"}}}

    assert tool_visibility(tool) == frozenset({"model", "app"})
    assert is_visible_to_model(tool)
    assert is_callable_from_app(tool)
    assert tool_ui_resource_uri(tool) == "ui://show"


def test_app_only_tool_is_not_model_visible():
    tool = {
        "name": "refresh",
        "_meta": {"ui": {"visibility": ["app"], "resourceUri": "ui://refresh"}},
    }

    assert tool_visibility(tool) == frozenset({"app"})
    assert not is_visible_to_model(tool)
    assert is_callable_from_app(tool)


def test_legacy_resource_uri_is_supported_only_for_ui_uris():
    assert tool_ui_resource_uri({"_meta": {"ui/resourceUri": "ui://legacy"}}) == "ui://legacy"
    assert tool_ui_resource_uri({"_meta": {"ui/resourceUri": "https://example.test/app"}}) is None
