"""YAML a member or a public repository wrote is read within bounds.

Anchors and merge keys let a few hundred bytes expand exponentially: a
26-level merge-key bomb in one SKILL.md frontmatter took about 45 s and 2 GB
through yaml.safe_load. The loader refuses aliases and merge keys outright
and stops at a node and a byte budget, so a refusal is immediate.
"""

import time

import pytest
from agentarea_common.utils.untrusted_yaml import UntrustedYamlError, load_untrusted_yaml


def _merge_bomb(levels: int) -> str:
    lines = ["a0: &a0 {x: 1}"]
    lines += [f"a{i}: &a{i} {{<<: [*a{i - 1}, *a{i - 1}]}}" for i in range(1, levels)]
    return "\n".join(lines)


def _alias_bomb(levels: int) -> str:
    lines = ['a0: &a0 ["x", "x"]']
    lines += [f"a{i}: &a{i} [*a{i - 1}, *a{i - 1}]" for i in range(1, levels)]
    return "\n".join(lines)


@pytest.mark.parametrize("bomb", [_merge_bomb(28), _alias_bomb(40)], ids=["merge", "alias"])
def test_a_bomb_is_refused_at_once(bomb):
    started = time.monotonic()

    with pytest.raises(UntrustedYamlError, match="alias"):
        load_untrusted_yaml(bomb, max_nodes=2000)

    assert time.monotonic() - started < 0.5


def test_a_merge_key_is_refused_without_any_alias():
    with pytest.raises(UntrustedYamlError, match="merge"):
        load_untrusted_yaml("base:\n  <<: {a: 1}\n  b: 2\n", max_nodes=2000)


def test_more_nodes_than_the_budget_are_refused():
    with pytest.raises(UntrustedYamlError, match="at most 50"):
        load_untrusted_yaml("items: [" + ", ".join(str(i) for i in range(100)) + "]", max_nodes=50)


def test_more_bytes_than_the_budget_are_refused_before_parsing():
    with pytest.raises(UntrustedYamlError, match="larger than"):
        load_untrusted_yaml("a: " + "x" * 2048, max_nodes=2000, max_bytes=1024)


def test_plain_yaml_reads_as_yaml():
    assert load_untrusted_yaml("name: pdf\ntags: [a, b]\nnested: {k: v}\n", max_nodes=2000) == {
        "name": "pdf",
        "tags": ["a", "b"],
        "nested": {"k": "v"},
    }


def test_a_refusal_is_a_yaml_error():
    import yaml

    assert issubclass(UntrustedYamlError, yaml.YAMLError)


@pytest.mark.parametrize(
    "nested",
    [
        "d: " + "[" * 400 + "]" * 400,
        "d: " + "{a: " * 400 + "1" + "}" * 400,
        "\n".join(f"{'  ' * i}k{i}:" for i in range(400)) + " 1",
    ],
    ids=["flow-sequence", "flow-mapping", "block-mapping"],
)
def test_deep_nesting_is_refused_as_untrusted_yaml(nested):
    # The composer recurses a few frames per level: 400 levels of brackets,
    # about 800 bytes, escaped as a RecursionError.
    started = time.monotonic()

    with pytest.raises(UntrustedYamlError, match="nested deeper than 64"):
        load_untrusted_yaml(nested, max_nodes=100_000)

    assert time.monotonic() - started < 0.5


def test_nesting_within_the_depth_loads():
    assert load_untrusted_yaml("d: " + "[" * 10 + "]" * 10, max_nodes=2000) == {
        "d": [[[[[[[[[[]]]]]]]]]]
    }
