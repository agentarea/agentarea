from types import SimpleNamespace

import pytest
from agentarea_agents.serving.revision_spec import RevisionSpec, apply_patch, diff_specs


def _agent(**overrides):
    fields = {
        "instruction": "Answer briefly.",
        "model_id": "11111111-1111-1111-1111-111111111111",
        "tools": [{"type": "mcp", "name": "search"}, {"type": "builtin", "name": "shell"}],
        "planning": False,
        "a2ui_enabled": None,
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


def test_spec_from_agent_copies_executable_fields_and_sorts_skills():
    spec = RevisionSpec.from_agent(_agent(), skill_ids=["b", "a"])

    assert spec.instruction == "Answer briefly."
    assert spec.tools == [{"type": "mcp", "name": "search"}, {"type": "builtin", "name": "shell"}]
    assert spec.skill_ids == ["a", "b"]


def test_non_list_tools_become_an_empty_list():
    assert RevisionSpec.from_agent(_agent(tools=None), skill_ids=[]).tools == []


def test_hash_ignores_tool_and_skill_order():
    a = RevisionSpec.from_agent(_agent(), skill_ids=["x", "y"])
    b = RevisionSpec.from_agent(
        _agent(tools=[{"type": "builtin", "name": "shell"}, {"type": "mcp", "name": "search"}]),
        skill_ids=["y", "x"],
    )

    assert a.config_hash() == b.config_hash()


def test_hash_moves_when_a2ui_changes():
    a = RevisionSpec.from_agent(_agent(a2ui_enabled=False), skill_ids=[])
    b = RevisionSpec.from_agent(_agent(a2ui_enabled=True), skill_ids=[])

    assert a.config_hash() != b.config_hash()


def test_dict_roundtrip():
    spec = RevisionSpec.from_agent(_agent(), skill_ids=["s1"])

    assert RevisionSpec.from_dict(spec.to_dict()) == spec


def test_diff_lists_only_changed_fields():
    a = RevisionSpec.from_agent(_agent(), skill_ids=["s1"])
    b = RevisionSpec.from_agent(_agent(instruction="Answer in detail."), skill_ids=["s1", "s2"])

    assert diff_specs(a, b) == [
        {"field": "instruction", "before": "Answer briefly.", "after": "Answer in detail."},
        {"field": "skill_ids", "before": ["s1"], "after": ["s1", "s2"]},
    ]


def test_apply_patch_replaces_named_fields_only():
    base = RevisionSpec.from_agent(_agent(), skill_ids=["s1"])

    patched = apply_patch(base, {"instruction": "New.", "skill_ids": ["s2", "s1"]})

    assert patched.instruction == "New."
    assert patched.skill_ids == ["s1", "s2"]
    assert patched.model_id == base.model_id


def test_apply_patch_rejects_unknown_fields():
    base = RevisionSpec.from_agent(_agent(), skill_ids=[])

    with pytest.raises(ValueError, match="name"):
        apply_patch(base, {"name": "renamed"})


def test_capability_expansion_detects_added_tool_skill_and_model_change():
    base = RevisionSpec.from_agent(_agent(), skill_ids=["s1"])

    assert not base.expands_capability_of(base)
    assert apply_patch(base, {"instruction": "x"}).expands_capability_of(base) is False
    assert apply_patch(base, {"skill_ids": ["s1", "s2"]}).expands_capability_of(base)
    assert apply_patch(base, {"model_id": "other"}).expands_capability_of(base)
    more_tools = [*base.tools, {"type": "mcp", "name": "mail"}]
    assert apply_patch(base, {"tools": more_tools}).expands_capability_of(base)
    assert apply_patch(base, {"tools": base.tools[:1]}).expands_capability_of(base) is False
