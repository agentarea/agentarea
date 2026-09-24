"""Existing agents keep their tools when ``allowed_tools: []`` changes meaning.

``[]`` was written under the reading "every tool", so the migration rewrites it
to ``null`` — the value that means every tool from now on.
"""

import importlib.util
from pathlib import Path

_MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "20260924_1000_allowed_tools_empty_means_none.py"
)
_spec = importlib.util.spec_from_file_location("_allowed_tools_migration", _MIGRATION)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
_empty_allowlists_to_null = _module._empty_allowlists_to_null


def test_empty_mcp_and_openapi_allowlists_become_null():
    tools = [
        {"type": "mcp", "name": "github", "settings": {"allowed_tools": []}},
        {"type": "openapi", "name": "billing", "settings": {"allowed_tools": [], "load_mode": "x"}},
    ]
    migrated, changed = _empty_allowlists_to_null(tools)

    assert changed is True
    assert migrated[0]["settings"]["allowed_tools"] is None
    assert migrated[1]["settings"] == {"allowed_tools": None, "load_mode": "x"}


def test_explicit_selections_and_other_tools_are_untouched():
    tools = [
        {"type": "mcp", "name": "github", "settings": {"allowed_tools": [{"tool_name": "search"}]}},
        {"type": "mcp", "name": "gitlab", "settings": {"allowed_tools": None}},
        {"type": "code", "name": "agentarea/shell", "settings": {"disabled_methods": []}},
        {"type": "mcp", "name": "linear"},
    ]
    migrated, changed = _empty_allowlists_to_null(tools)

    assert changed is False
    assert migrated == tools


def test_non_list_tools_are_left_alone():
    assert _empty_allowlists_to_null(None) == (None, False)
    assert _empty_allowlists_to_null({"mcp_servers": []}) == ({"mcp_servers": []}, False)
