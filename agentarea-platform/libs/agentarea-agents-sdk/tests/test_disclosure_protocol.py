"""Protocol shape, type defaults, and registry behavior for disclosure module."""

import pytest

from agentarea_agents_sdk.tools.disclosure import (
    DisclosureContext,
    ExplicitPolicy,
    NamedLookupPolicy,
    Partition,
    RevealRequest,
    RevealResult,
    ToolCandidate,
    ToolDisclosurePolicy,
    list_policies,
    policy_from_config,
    register_policy,
)


def test_protocol_runtime_checkable_for_explicit():
    assert isinstance(ExplicitPolicy(), ToolDisclosurePolicy)


def test_protocol_runtime_checkable_for_named_lookup():
    assert isinstance(NamedLookupPolicy(), ToolDisclosurePolicy)


def test_protocol_rejects_non_policy_object():
    class NotAPolicy:
        def partition(self, *_):
            return None

    # Missing render_catalog/get_meta_tool_definitions/reveal — protocol mismatch.
    assert not isinstance(NotAPolicy(), ToolDisclosurePolicy)


def test_disclosure_context_defaults():
    ctx = DisclosureContext()
    assert ctx.model_name == ""
    assert ctx.context_window == 0
    assert ctx.iteration == 0


def test_partition_defaults_empty():
    p = Partition()
    assert p.explicit == []
    assert p.deferred == []


def test_reveal_request_defaults_empty_names():
    assert RevealRequest().tool_names == []


def test_reveal_result_defaults_empty():
    r = RevealResult()
    assert r.revealed == []
    assert r.matched_names == []
    assert r.unknown_names == []
    assert r.message == ""


def test_tool_candidate_defaults():
    c = ToolCandidate(name="x", description="y", schema={"a": 1})
    assert c.connection_id == ""
    assert c.source_type == "openapi"


def test_registry_lists_builtin_policies():
    names = list_policies()
    assert "explicit" in names
    assert "named_lookup" in names
    assert "searchable" in names


def test_policy_from_config_none_returns_explicit():
    assert isinstance(policy_from_config(None), ExplicitPolicy)


def test_policy_from_config_string_explicit():
    assert isinstance(policy_from_config("explicit"), ExplicitPolicy)


def test_policy_from_config_string_named_lookup():
    assert isinstance(policy_from_config("named_lookup"), NamedLookupPolicy)


def test_policy_from_config_searchable_alias():
    """`searchable` is the YAML-shorthand alias for NamedLookupPolicy."""
    assert isinstance(policy_from_config("searchable"), NamedLookupPolicy)


def test_policy_from_config_dict_form():
    assert isinstance(policy_from_config({"name": "named_lookup"}), NamedLookupPolicy)


def test_policy_from_config_unknown_raises():
    with pytest.raises(ValueError, match="Unknown disclosure policy"):
        policy_from_config("nonexistent")


def test_policy_from_config_dict_without_name_raises():
    with pytest.raises(ValueError, match="non-empty 'name'"):
        policy_from_config({})


def test_policy_from_config_invalid_type_raises():
    with pytest.raises(ValueError, match="must be None, str, or dict"):
        policy_from_config(123)  # type: ignore[arg-type]


def test_register_policy_round_trip():
    """Custom policies can register and resolve via the same factory entrypoint."""

    class FakePolicy:
        def partition(self, *a, **k):
            return Partition()

        def render_catalog(self, *a, **k):
            return ""

        def get_meta_tool_definitions(self, *a, **k):
            return []

        def reveal(self, *a, **k):
            return RevealResult()

    register_policy("test_fake", FakePolicy)
    assert "test_fake" in list_policies()
    assert isinstance(policy_from_config("test_fake"), FakePolicy)
