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


def wire_di(
    deployment_mode: str = "oss",
    backend: str = "disabled",
    openfga_impl: PermissionService | None = None,
    keto_impl: PermissionService | None = None,
):
    """Simulate the startup wiring logic (mirrors apps/api + apps/worker main.py).

    PermissionService is a SELECTOR: an explicit ACCESS_CONTROL_BACKEND wins over a
    merely-installed "permissions" extension; the extension is only a fallback used
    when no concrete backend is selected.
    """
    from agentarea_common.extensions import discover_extensions

    discover_extensions()

    container = get_container()

    # Feature service
    mode = DeploymentMode(deployment_mode)
    container.register_singleton(FeatureService, FeatureService(mode=mode))

    # Permission service — explicit backend is authoritative; extension is fallback.
    perm_factory = ExtensionRegistry.get_factory("permissions")
    if backend == "openfga" and openfga_impl is not None:
        container.register_singleton(PermissionService, openfga_impl)
    elif backend == "keto" and keto_impl is not None:
        container.register_singleton(PermissionService, keto_impl)
    elif perm_factory:
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
    """With no explicit backend selected, a permissions extension is the fallback."""

    class FakePermissionService(PermissionService):
        async def check(self, user_id, permission, resource_type, resource_id):
            return False

    ExtensionRegistry.register("permissions", FakePermissionService)
    wire_di("enterprise")

    container = get_container()
    perm = container.get(PermissionService)
    assert isinstance(perm, FakePermissionService)


@pytest.mark.flow(MainFlow.EXTENSION_CONTRACT)
def test_explicit_backend_shadows_extension():
    """An EXPLICIT ACCESS_CONTROL_BACKEND must win over an installed extension.

    Regression guard: a registered "permissions" extension used to be checked
    first and silently overrode the configured backend (an installed keto
    extension shadowed ACCESS_CONTROL_BACKEND=openfga, so OpenFGA never enforced).
    """

    class FakeExtensionPermissionService(PermissionService):
        async def check(self, user_id, permission, resource_type, resource_id):
            return False

    class FakeOpenFGAPermissionService(PermissionService):
        async def check(self, user_id, permission, resource_type, resource_id):
            return True

    ExtensionRegistry.register("permissions", FakeExtensionPermissionService)
    wire_di("enterprise", backend="openfga", openfga_impl=FakeOpenFGAPermissionService())

    container = get_container()
    perm = container.get(PermissionService)
    assert isinstance(perm, FakeOpenFGAPermissionService)
    assert not isinstance(perm, FakeExtensionPermissionService)
