import pytest
from agentarea_common.extensions.registry import ExtensionRegistry


@pytest.fixture(autouse=True)
def clean_registry():
    """Clear registry between tests to avoid state leaks."""
    ExtensionRegistry.clear()
    yield
    ExtensionRegistry.clear()


def dummy_factory():
    return "instance"


def test_register_and_get_factory():
    ExtensionRegistry.register("permissions", dummy_factory)
    assert ExtensionRegistry.get_factory("permissions") is dummy_factory


def test_get_factory_returns_none_for_unknown():
    assert ExtensionRegistry.get_factory("unknown") is None


def test_has_returns_true_for_registered():
    ExtensionRegistry.register("permissions", dummy_factory)
    assert ExtensionRegistry.has("permissions") is True


def test_has_returns_false_for_unregistered():
    assert ExtensionRegistry.has("unknown") is False


def test_clear_removes_all():
    ExtensionRegistry.register("permissions", dummy_factory)
    ExtensionRegistry.clear()
    assert ExtensionRegistry.has("permissions") is False


def test_register_overwrites_existing():
    def other_factory():
        return "other"
    ExtensionRegistry.register("permissions", dummy_factory)
    ExtensionRegistry.register("permissions", other_factory)
    assert ExtensionRegistry.get_factory("permissions") is other_factory
