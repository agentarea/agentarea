# tests/unit/test_extension_wiring.py
import pytest
from agentarea_common.auth.permission import PermissionService
from agentarea_common.auth.workspace_permission import WorkspaceScopedPermissionService
from agentarea_common.di.container import get_container
from agentarea_common.extensions.registry import ExtensionRegistry
from agentarea_common.features.service import DeploymentMode, FeatureService
from agentarea_common.testing.flows import MainFlow


@pytest.fixture(autouse=True)
def clean():
    ExtensionRegistry.clear()
    get_container().clear()
    yield
    ExtensionRegistry.clear()
    get_container().clear()


def wire_di(deployment_mode: str = "oss"):
    """Simulate the startup wiring logic."""
    from agentarea_common.extensions import discover_extensions

    discover_extensions()

    container = get_container()

    # Feature service
    mode = DeploymentMode(deployment_mode)
    container.register_singleton(FeatureService, FeatureService(mode=mode))

    # Permission service — enterprise factory overrides OSS default
    perm_factory = ExtensionRegistry.get_factory("permissions")
    if perm_factory:
        container.register_factory(PermissionService, perm_factory)
    else:
        container.register_singleton(PermissionService, WorkspaceScopedPermissionService())


def test_oss_wiring_uses_workspace_permission():
    wire_di("oss")
    container = get_container()
    perm = container.get(PermissionService)
    assert isinstance(perm, WorkspaceScopedPermissionService)


def test_oss_wiring_registers_feature_service():
    wire_di("oss")
    container = get_container()
    fs = container.get(FeatureService)
    assert fs.mode == DeploymentMode.OSS


@pytest.mark.flow(MainFlow.EXTENSION_CONTRACT)
def test_enterprise_factory_overrides_default():
    class FakePermissionService(PermissionService):
        async def check(self, user_id, permission, resource_type, resource_id):
            return False

    ExtensionRegistry.register("permissions", FakePermissionService)
    wire_di("enterprise")

    container = get_container()
    perm = container.get(PermissionService)
    assert isinstance(perm, FakePermissionService)
