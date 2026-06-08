"""Unit tests for the catalog-projection ``is_builtin`` predicate (ADR-003).

There is no longer a ``source`` provenance column and there are no persisted
built-in rows. "Built-in" means a transient, read-only catalog *projection*,
marked with ``is_catalog = True``. Copy-on-write forks carry a
``registry_item_id`` link to the catalog item they were forked from, but are
persisted, user-owned content and are therefore NOT built-in.
"""

from types import SimpleNamespace

from agentarea_common.base import is_builtin


def test_is_builtin_true_when_is_catalog_set():
    assert is_builtin(SimpleNamespace(is_catalog=True)) is True


def test_is_builtin_false_when_is_catalog_false():
    assert is_builtin(SimpleNamespace(is_catalog=False)) is False


def test_is_builtin_false_when_is_catalog_missing():
    assert is_builtin(SimpleNamespace()) is False


def test_forked_entity_is_not_builtin():
    """A fork carries registry_item_id but is owned content -> not built-in."""
    fork = SimpleNamespace(registry_item_id="ri-1", is_catalog=False)
    assert is_builtin(fork) is False


def test_catalog_projection_is_builtin():
    """A catalog projection has is_catalog True even with a registry_item_id."""
    projection = SimpleNamespace(registry_item_id="ri-1", is_catalog=True)
    assert is_builtin(projection) is True
