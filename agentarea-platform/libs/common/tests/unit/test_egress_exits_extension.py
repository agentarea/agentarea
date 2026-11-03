"""Egress exits exist on a deployment only when an extension enforces them."""

import pytest
from agentarea_common.extensions.egress_exits import (
    EGRESS_EXITS_EXTENSION,
    EgressExitsNotSupportedError,
    egress_exits_supported,
    require_egress_exits,
)
from agentarea_common.extensions.registry import ExtensionRegistry


@pytest.fixture(autouse=True)
def _clean_registry():
    ExtensionRegistry.clear()
    yield
    ExtensionRegistry.clear()


def test_without_the_extension_a_deployment_has_no_egress_exits():
    assert egress_exits_supported() is False
    with pytest.raises(EgressExitsNotSupportedError, match="enterprise"):
        require_egress_exits()


def test_an_installed_extension_turns_them_on():
    ExtensionRegistry.register(EGRESS_EXITS_EXTENSION, lambda: True)

    assert egress_exits_supported() is True
    require_egress_exits()


def test_an_installed_extension_that_failed_to_load_is_an_error_not_an_absence():
    ExtensionRegistry.record_failure(EGRESS_EXITS_EXTENSION, "ImportError: boom")

    with pytest.raises(RuntimeError, match="failed to load"):
        egress_exits_supported()
