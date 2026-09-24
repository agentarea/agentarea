"""Pure helpers for MCP Apps tool metadata and audience visibility."""

from collections.abc import Mapping
from typing import Any

UI_RESOURCE_MIME_TYPE = "text/html;profile=mcp-app"
_DEFAULT_VISIBILITY = frozenset({"model", "app"})


def _ui_metadata(tool: Mapping[str, Any]) -> Mapping[str, Any] | None:
    metadata = tool.get("_meta")
    if not isinstance(metadata, Mapping):
        return None
    ui = metadata.get("ui")
    return ui if isinstance(ui, Mapping) else None


def tool_ui_resource_uri(tool: Mapping[str, Any]) -> str | None:
    """Return the valid MCP Apps resource URI advertised by a tool."""
    metadata = tool.get("_meta")
    if not isinstance(metadata, Mapping):
        return None

    ui = metadata.get("ui")
    if isinstance(ui, Mapping):
        resource_uri = ui.get("resourceUri")
        if isinstance(resource_uri, str) and resource_uri.startswith("ui://"):
            return resource_uri

    legacy_resource_uri = metadata.get("ui/resourceUri")
    if isinstance(legacy_resource_uri, str) and legacy_resource_uri.startswith("ui://"):
        return legacy_resource_uri
    return None


def tool_visibility(tool: Mapping[str, Any]) -> frozenset[str]:
    """Return audiences allowed to see a tool, defaulting to both audiences."""
    ui = _ui_metadata(tool)
    if ui is None or "visibility" not in ui:
        return _DEFAULT_VISIBILITY

    visibility = ui.get("visibility")
    if isinstance(visibility, str):
        return frozenset({visibility})
    if isinstance(visibility, (list, tuple, set, frozenset)):
        return frozenset(value for value in visibility if isinstance(value, str))
    return frozenset()


def is_visible_to_model(tool: Mapping[str, Any]) -> bool:
    return "model" in tool_visibility(tool)


def is_callable_from_app(tool: Mapping[str, Any]) -> bool:
    return "app" in tool_visibility(tool)
