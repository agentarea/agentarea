"""The approval migration must read the same names the runtime sync does.

The migration is frozen at its revision, so its target extraction is inlined
rather than imported. That freezes a second copy of the naming rule — these
tests pin it against the same cases as the live sync so the two cannot drift into
the very name mismatch (namespace vs LLM-facing) the whole change exists to fix.
"""

import importlib.util
from pathlib import Path

_MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "20260719_0100_approval_toggle_to_rules.py"
)
_spec = importlib.util.spec_from_file_location("_approval_migration", _MIGRATION)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
_targets_and_stripped = _module._targets_and_stripped


def test_code_tool_namespace_collapses_and_flag_is_stripped():
    tools = [
        {
            "name": "agentarea/shell",
            "type": "code",
            "settings": {
                "requires_user_confirmation": True,
            },
        }
    ]
    targets, stripped, changed = _targets_and_stripped(tools)

    assert targets == {"tool:shell"}
    assert changed is True
    assert "requires_user_confirmation" not in stripped[0]["settings"]


def test_mcp_permission_uses_the_raw_name():
    tools = [
        {
            "name": "github",
            "type": "mcp",
            "settings": {
                "allowed_tools": [
                    {"tool_name": "create_issue", "requires_user_confirmation": True},
                    {"tool_name": "list_issues", "requires_user_confirmation": False},
                ]
            },
        }
    ]
    targets, stripped, changed = _targets_and_stripped(tools)

    assert targets == {"tool:create_issue"}
    assert changed is True
    allowed = stripped[0]["settings"]["allowed_tools"]
    assert allowed == [{"tool_name": "create_issue"}, {"tool_name": "list_issues"}]


def test_unset_flags_produce_no_targets_and_no_change():
    tools = [
        {"name": "agentarea/files", "type": "code", "settings": {"disabled_methods": ["x"]}},
        {"name": "github", "type": "mcp", "settings": {"allowed_tools": [{"tool_name": "a"}]}},
    ]
    targets, _stripped, changed = _targets_and_stripped(tools)

    assert targets == set()
    assert changed is False


def test_a_false_flag_is_stripped_without_producing_a_target():
    tools = [
        {
            "name": "agentarea/shell",
            "type": "code",
            "settings": {
                "requires_user_confirmation": False,
            },
        }
    ]
    targets, stripped, changed = _targets_and_stripped(tools)

    assert targets == set()
    assert changed is True
    assert "requires_user_confirmation" not in stripped[0]["settings"]


def test_non_list_tools_are_left_alone():
    assert _targets_and_stripped(None) == (set(), [], False)
    assert _targets_and_stripped({}) == (set(), [], False)
