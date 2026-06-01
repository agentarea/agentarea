"""Behavior of ExplicitPolicy and NamedLookupPolicy concrete strategies."""

from agentarea_agents_sdk.tools.disclosure import (
    LOAD_TOOLS_NAME,
    DisclosureContext,
    ExplicitPolicy,
    NamedLookupPolicy,
    RevealRequest,
    ToolCandidate,
)

CTX = DisclosureContext()


def _candidate(name: str, conn: str = "stripe-api", desc: str = "") -> ToolCandidate:
    return ToolCandidate(
        name=name,
        description=desc or f"Operation {name}",
        schema={
            "type": "function",
            "function": {
                "name": name,
                "description": desc or f"Operation {name}",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        },
        connection_id=conn,
    )


# ---- ExplicitPolicy ----------------------------------------------------------


def test_explicit_partition_keeps_all_schemas_explicit():
    cands = [_candidate("a"), _candidate("b")]
    p = ExplicitPolicy().partition(cands, CTX)
    assert len(p.explicit) == 2
    assert p.deferred == []
    assert p.explicit[0]["function"]["name"] == "a"


def test_explicit_render_catalog_empty():
    assert ExplicitPolicy().render_catalog([_candidate("a")], CTX) == ""


def test_explicit_no_meta_tools():
    assert ExplicitPolicy().get_meta_tool_definitions(CTX) == []


def test_explicit_reveal_is_noop():
    r = ExplicitPolicy().reveal(RevealRequest(tool_names=["a"]), [_candidate("a")], CTX)
    assert r.revealed == []
    assert r.matched_names == []
    assert r.unknown_names == []


# ---- NamedLookupPolicy -------------------------------------------------------


def test_named_lookup_defers_all():
    cands = [_candidate("a"), _candidate("b")]
    p = NamedLookupPolicy().partition(cands, CTX)
    assert p.explicit == []
    assert [c.name for c in p.deferred] == ["a", "b"]


def test_named_lookup_catalog_empty_when_no_deferred():
    assert NamedLookupPolicy().render_catalog([], CTX) == ""


def test_named_lookup_catalog_groups_by_connection():
    cands = [
        _candidate("createCharge", conn="stripe-api", desc="Create a charge."),
        _candidate("listCustomers", conn="stripe-api", desc="List customers."),
        _candidate("listRepos", conn="github-api", desc="List repos."),
    ]
    text = NamedLookupPolicy().render_catalog(cands, CTX)
    assert "## Available OpenAPI Operations" in text
    assert "[github-api]" in text
    assert "[stripe-api]" in text
    assert "- createCharge: Create a charge." in text
    assert "- listCustomers: List customers." in text
    assert "- listRepos: List repos." in text
    # github-api comes first alphabetically
    assert text.index("[github-api]") < text.index("[stripe-api]")


def test_named_lookup_catalog_handles_missing_description():
    cand = ToolCandidate(name="foo", description="", schema={}, connection_id="api")
    text = NamedLookupPolicy().render_catalog([cand], CTX)
    assert "- foo" in text
    assert "- foo:" not in text


def test_named_lookup_catalog_takes_first_line_of_multiline_description():
    cand = _candidate("foo", desc="First line.\nSecond line should not appear.")
    text = NamedLookupPolicy().render_catalog([cand], CTX)
    assert "First line." in text
    assert "Second line" not in text


def test_named_lookup_catalog_handles_whitespace_only_description():
    """A truthy-but-empty description (e.g. \"  \\n\") used to crash on splitlines()[0]."""
    cand = ToolCandidate(name="foo", description="   \n", schema={}, connection_id="api")
    text = NamedLookupPolicy().render_catalog([cand], CTX)
    assert "- foo" in text
    assert "- foo:" not in text


def test_named_lookup_meta_tool_shape():
    defs = NamedLookupPolicy().get_meta_tool_definitions(CTX)
    assert len(defs) == 1
    fn = defs[0]
    assert fn["type"] == "function"
    assert fn["function"]["name"] == LOAD_TOOLS_NAME
    params = fn["function"]["parameters"]
    assert params["type"] == "object"
    assert params["required"] == ["tool_names"]
    assert params["properties"]["tool_names"]["type"] == "array"
    assert params["properties"]["tool_names"]["items"]["type"] == "string"


def test_named_lookup_reveal_matches_known_names():
    pool = [_candidate("a"), _candidate("b"), _candidate("c")]
    r = NamedLookupPolicy().reveal(RevealRequest(tool_names=["a", "c"]), pool, CTX)
    assert r.matched_names == ["a", "c"]
    assert r.unknown_names == []
    assert [s["function"]["name"] for s in r.revealed] == ["a", "c"]
    assert "Loaded 2 operations" in r.message


def test_named_lookup_reveal_reports_unknown_with_valid_preview():
    pool = [_candidate("known")]
    r = NamedLookupPolicy().reveal(
        RevealRequest(tool_names=["known", "missing"]), pool, CTX
    )
    assert r.matched_names == ["known"]
    assert r.unknown_names == ["missing"]
    assert "Unknown names: ['missing']" in r.message
    assert "known" in r.message


def test_named_lookup_reveal_caps_valid_examples_at_20():
    pool = [_candidate(f"op_{i:03d}") for i in range(50)]
    r = NamedLookupPolicy().reveal(
        RevealRequest(tool_names=["nope"]), pool, CTX
    )
    assert r.unknown_names == ["nope"]
    assert "more available" in r.message


def test_named_lookup_reveal_empty_request_returns_empty():
    pool = [_candidate("a")]
    r = NamedLookupPolicy().reveal(RevealRequest(tool_names=[]), pool, CTX)
    assert r.matched_names == []
    assert r.unknown_names == []
    assert r.revealed == []
