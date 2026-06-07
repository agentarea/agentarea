"""Unit tests for the SourceKind provenance enum and is_builtin predicate."""

from types import SimpleNamespace

from agentarea_common.base import SourceKind, is_builtin


def test_source_kind_values():
    assert SourceKind.OFFICIAL == "official"
    assert SourceKind.WORKSPACE_CUSTOM == "workspace_custom"
    assert SourceKind.IMPORTED == "imported"


def test_is_builtin_true_for_official():
    assert is_builtin(SimpleNamespace(source=SourceKind.OFFICIAL)) is True
    # Plain string value also counts (StrEnum compares equal to its value).
    assert is_builtin(SimpleNamespace(source="official")) is True


def test_is_builtin_false_for_workspace_custom():
    assert is_builtin(SimpleNamespace(source=SourceKind.WORKSPACE_CUSTOM)) is False
    assert is_builtin(SimpleNamespace(source="workspace_custom")) is False


def test_is_builtin_false_for_imported():
    assert is_builtin(SimpleNamespace(source=SourceKind.IMPORTED)) is False


def test_is_builtin_false_when_source_missing():
    assert is_builtin(SimpleNamespace()) is False
    assert is_builtin(SimpleNamespace(source=None)) is False
