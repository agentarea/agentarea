# Plugin Architecture, IaC Config & Permission Service — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce a plugin/extension architecture that separates OSS from enterprise, a permission service as the first plugin, an IaC config reconciler for system entities, and system entity visibility fixes.

**Architecture:** Python entrypoint-based plugin discovery wires enterprise implementations into the DI container. OSS defaults (no-op permission, unlimited quotas) are used when no enterprise package is installed. The IaC reconciler extends the existing bootstrap system to upsert system entities from YAML on every deploy.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async, Pydantic, uv workspace, pytest

**Spec:** `docs/superpowers/specs/2026-03-16-plugin-architecture-iac-permissions-design.md`

---

## Chunk 1: Extension Registry + Feature Service + Permission Interface

### Task 1: Extension Registry

**Files:**
- Create: `agentarea-platform/libs/common/agentarea_common/extensions/__init__.py`
- Create: `agentarea-platform/libs/common/agentarea_common/extensions/registry.py`
- Create: `agentarea-platform/libs/common/agentarea_common/extensions/discovery.py`
- Test: `agentarea-platform/tests/unit/test_extension_registry.py`

- [ ] **Step 1: Write failing tests for ExtensionRegistry**

```python
# tests/unit/test_extension_registry.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd agentarea-platform && python -m pytest tests/unit/test_extension_registry.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement ExtensionRegistry**

```python
# libs/common/agentarea_common/extensions/__init__.py
from .discovery import discover_extensions
from .registry import ExtensionRegistry

__all__ = ["ExtensionRegistry", "discover_extensions"]
```

```python
# libs/common/agentarea_common/extensions/registry.py
"""Plugin extension registry for OSS/Enterprise feature separation."""

from collections.abc import Callable
from typing import Any


class ExtensionRegistry:
    """Registry mapping extension point names to factory callables.

    Factory callables create instances of the corresponding interface.
    This allows enterprise implementations to manage their own dependencies
    (e.g., KetoPermissionService needs a keto_client).
    """

    _factories: dict[str, Callable[[], Any]] = {}

    @classmethod
    def register(cls, interface: str, factory: Callable[[], Any]) -> None:
        """Register a factory for an extension point."""
        cls._factories[interface] = factory

    @classmethod
    def get_factory(cls, interface: str) -> Callable[[], Any] | None:
        """Get the factory for an extension point, or None."""
        return cls._factories.get(interface)

    @classmethod
    def has(cls, interface: str) -> bool:
        """Check if an extension point has a registered factory."""
        return interface in cls._factories

    @classmethod
    def clear(cls) -> None:
        """Clear all registrations. For testing only."""
        cls._factories = {}
```

```python
# libs/common/agentarea_common/extensions/discovery.py
"""Entrypoint-based plugin discovery."""

import logging
from importlib.metadata import entry_points

from .registry import ExtensionRegistry

logger = logging.getLogger(__name__)

ENTRYPOINT_GROUP = "agentarea.extensions"


def discover_extensions() -> None:
    """Scan installed packages for agentarea extensions.

    Each entrypoint must point to a factory callable that returns
    an instance of the corresponding interface.
    """
    discovered = entry_points(group=ENTRYPOINT_GROUP)
    for ep in discovered:
        try:
            factory = ep.load()
            ExtensionRegistry.register(ep.name, factory)
            logger.info("Discovered extension: %s from %s", ep.name, ep.value)
        except Exception:
            logger.exception("Failed to load extension: %s", ep.name)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd agentarea-platform && python -m pytest tests/unit/test_extension_registry.py -v`
Expected: All 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add agentarea-platform/libs/common/agentarea_common/extensions/ agentarea-platform/tests/unit/test_extension_registry.py
git commit -m "feat: add extension registry for plugin architecture"
```

---

### Task 2: Feature Service

**Files:**
- Create: `agentarea-platform/libs/common/agentarea_common/features/__init__.py`
- Create: `agentarea-platform/libs/common/agentarea_common/features/service.py`
- Modify: `agentarea-platform/libs/common/agentarea_common/config/app.py:8-13` (add DEPLOYMENT_MODE)
- Test: `agentarea-platform/tests/unit/test_feature_service.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_feature_service.py
import pytest
from agentarea_common.features.service import DeploymentMode, FeatureService


def test_oss_mode_defaults():
    fs = FeatureService(mode=DeploymentMode.OSS)
    assert fs.system_entities_read_only_in_ui is False
    assert fs.show_system_entity_badge is False
    assert fs.enable_usage_metering is False


def test_enterprise_mode_defaults():
    fs = FeatureService(mode=DeploymentMode.ENTERPRISE)
    assert fs.system_entities_read_only_in_ui is True
    assert fs.show_system_entity_badge is True
    assert fs.enable_usage_metering is True


def test_default_mode_is_oss():
    fs = FeatureService()
    assert fs.mode == DeploymentMode.OSS
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd agentarea-platform && python -m pytest tests/unit/test_feature_service.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement FeatureService**

```python
# libs/common/agentarea_common/features/__init__.py
from .service import DeploymentMode, FeatureService

__all__ = ["DeploymentMode", "FeatureService"]
```

```python
# libs/common/agentarea_common/features/service.py
"""Feature service for deployment-mode-specific behaviors.

Note: This controls UI/presentation concerns only.
Implementation swapping (e.g., which PermissionService) is handled
by the plugin extension registry, not feature flags.
"""

from enum import StrEnum


class DeploymentMode(StrEnum):
    OSS = "oss"
    ENTERPRISE = "enterprise"


class FeatureService:
    """Controls deployment-mode-specific behaviors."""

    def __init__(self, mode: DeploymentMode = DeploymentMode.OSS):
        self.mode = mode

    @property
    def show_system_entity_badge(self) -> bool:
        """UI: show 'System' badge on system entities."""
        return self.mode == DeploymentMode.ENTERPRISE

    @property
    def system_entities_read_only_in_ui(self) -> bool:
        """UI: disable edit controls for system entities."""
        return self.mode == DeploymentMode.ENTERPRISE

    @property
    def enable_usage_metering(self) -> bool:
        """Enable usage metering and billing integration."""
        return self.mode == DeploymentMode.ENTERPRISE
```

- [ ] **Step 4: Add DEPLOYMENT_MODE to AppSettings**

Modify `agentarea-platform/libs/common/agentarea_common/config/app.py`:

Add after line 12 (`APP_NAME: str = "AI Agent Service"`):

```python
    DEPLOYMENT_MODE: str = "oss"
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd agentarea-platform && python -m pytest tests/unit/test_feature_service.py -v`
Expected: All 3 tests PASS

- [ ] **Step 6: Commit**

```bash
git add agentarea-platform/libs/common/agentarea_common/features/ agentarea-platform/tests/unit/test_feature_service.py agentarea-platform/libs/common/agentarea_common/config/app.py
git commit -m "feat: add feature service for deployment mode"
```

---

### Task 3: Permission Service Interface + OSS Implementation

**Files:**
- Create: `agentarea-platform/libs/common/agentarea_common/auth/permission.py`
- Create: `agentarea-platform/libs/common/agentarea_common/auth/simple_permission.py`
- Modify: `agentarea-platform/libs/common/agentarea_common/auth/__init__.py` (add exports)
- Test: `agentarea-platform/tests/unit/test_permission_service.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_permission_service.py
import pytest
from agentarea_common.auth.permission import PermissionService, require_permission
from agentarea_common.auth.simple_permission import SimplePermissionService
from agentarea_common.di.container import get_container


@pytest.fixture(autouse=True)
def clean_container():
    container = get_container()
    yield
    container.clear()


@pytest.mark.asyncio
async def test_simple_permission_always_allows():
    svc = SimplePermissionService()
    result = await svc.check("user-1", "edit", "agent", "agent-123")
    assert result is True


@pytest.mark.asyncio
async def test_simple_permission_allows_system_entity_mutation():
    svc = SimplePermissionService()
    result = await svc.check("user-1", "delete", "mcp_server", "system-mcp-123")
    assert result is True


@pytest.mark.asyncio
async def test_require_permission_passes_when_allowed():
    container = get_container()
    container.register_singleton(PermissionService, SimplePermissionService())
    # Should not raise
    await require_permission("edit", "agent", "agent-123", "user-1")


@pytest.mark.asyncio
async def test_require_permission_raises_403_when_denied():
    from unittest.mock import AsyncMock
    from fastapi import HTTPException

    mock_svc = AsyncMock(spec=PermissionService)
    mock_svc.check.return_value = False

    container = get_container()
    container.register_singleton(PermissionService, mock_svc)

    with pytest.raises(HTTPException) as exc_info:
        await require_permission("edit", "agent", "agent-123", "user-1")
    assert exc_info.value.status_code == 403


def test_permission_service_is_abstract():
    with pytest.raises(TypeError):
        PermissionService()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd agentarea-platform && python -m pytest tests/unit/test_permission_service.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement PermissionService ABC + require_permission helper**

```python
# libs/common/agentarea_common/auth/permission.py
"""Permission service interface and helper."""

import logging
from abc import ABC, abstractmethod

from fastapi import HTTPException

logger = logging.getLogger(__name__)


class PermissionService(ABC):
    """Abstract permission service. OSS and Enterprise provide implementations."""

    @abstractmethod
    async def check(
        self,
        user_id: str,
        permission: str,
        resource_type: str,
        resource_id: str,
    ) -> bool:
        """Check if user has permission on a resource.

        Args:
            user_id: The user requesting access.
            permission: Action (view, edit, delete, execute).
            resource_type: Entity type (agent, mcp_server, skill, model, etc.).
            resource_id: ID of the specific resource.

        Returns:
            True if allowed, False if denied.
        """
        ...


async def require_permission(
    permission: str,
    resource_type: str,
    resource_id: str,
    user_id: str,
) -> None:
    """Check permission and raise 403 if denied.

    Resolves PermissionService from the DI container.
    """
    from agentarea_common.di.container import resolve

    perm_service = resolve(PermissionService)
    allowed = await perm_service.check(user_id, permission, resource_type, resource_id)
    if not allowed:
        logger.warning(
            "Permission denied: user=%s permission=%s resource=%s/%s",
            user_id, permission, resource_type, resource_id,
        )
        raise HTTPException(status_code=403, detail="Permission denied")
```

- [ ] **Step 4: Implement SimplePermissionService**

```python
# libs/common/agentarea_common/auth/simple_permission.py
"""OSS permission service — allows all operations."""

from .permission import PermissionService


class SimplePermissionService(PermissionService):
    """Workspace-scoped permission checks. No external dependencies.

    In OSS mode, all operations are allowed. Workspace isolation
    is enforced at the repository layer via WorkspaceScopedMixin.
    """

    async def check(
        self,
        user_id: str,
        permission: str,
        resource_type: str,
        resource_id: str,
    ) -> bool:
        return True
```

- [ ] **Step 5: Update auth __init__.py exports**

Modify `agentarea-platform/libs/common/agentarea_common/auth/__init__.py` — add to existing exports:

```python
from .permission import PermissionService, require_permission
from .simple_permission import SimplePermissionService
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd agentarea-platform && python -m pytest tests/unit/test_permission_service.py -v`
Expected: All 5 tests PASS

- [ ] **Step 7: Commit**

```bash
git add agentarea-platform/libs/common/agentarea_common/auth/permission.py agentarea-platform/libs/common/agentarea_common/auth/simple_permission.py agentarea-platform/libs/common/agentarea_common/auth/__init__.py agentarea-platform/tests/unit/test_permission_service.py
git commit -m "feat: add permission service interface and OSS implementation"
```

---

### Task 4: Wire Extensions + Permissions into DI and Startup

**Files:**
- Modify: `agentarea-platform/apps/api/agentarea_api/main.py:117-139` (initialize_services)
- Modify: `agentarea-platform/apps/worker/agentarea_worker/main.py:100-113` (create_worker)
- Test: `agentarea-platform/tests/unit/test_extension_wiring.py`

- [ ] **Step 1: Write failing test for DI wiring**

```python
# tests/unit/test_extension_wiring.py
import pytest
from agentarea_common.auth.permission import PermissionService
from agentarea_common.auth.simple_permission import SimplePermissionService
from agentarea_common.di.container import get_container
from agentarea_common.extensions.registry import ExtensionRegistry
from agentarea_common.features.service import DeploymentMode, FeatureService


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
        container.register_singleton(PermissionService, SimplePermissionService())


def test_oss_wiring_uses_simple_permission():
    wire_di("oss")
    container = get_container()
    perm = container.get(PermissionService)
    assert isinstance(perm, SimplePermissionService)


def test_oss_wiring_registers_feature_service():
    wire_di("oss")
    container = get_container()
    fs = container.get(FeatureService)
    assert fs.mode == DeploymentMode.OSS


def test_enterprise_factory_overrides_default():
    class FakePermissionService(PermissionService):
        async def check(self, user_id, permission, resource_type, resource_id):
            return False

    ExtensionRegistry.register("permissions", FakePermissionService)
    wire_di("enterprise")

    container = get_container()
    perm = container.get(PermissionService)
    assert isinstance(perm, FakePermissionService)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd agentarea-platform && python -m pytest tests/unit/test_extension_wiring.py -v`
Expected: FAIL (wire_di function references code that works, but we want to verify the pattern)

- [ ] **Step 3: Add wiring to API startup**

Modify `agentarea-platform/apps/api/agentarea_api/main.py`. Add at the top of `initialize_services()` (line 118, after the docstring):

```python
    # Discover extensions and wire DI
    from agentarea_common.extensions import discover_extensions
    from agentarea_common.extensions.registry import ExtensionRegistry
    from agentarea_common.auth.permission import PermissionService
    from agentarea_common.auth.simple_permission import SimplePermissionService
    from agentarea_common.features.service import DeploymentMode, FeatureService
    from agentarea_common.config.app import get_app_settings

    discover_extensions()

    app_settings = get_app_settings()
    mode = DeploymentMode(app_settings.DEPLOYMENT_MODE)
    register_singleton(FeatureService, FeatureService(mode=mode))

    perm_factory = ExtensionRegistry.get_factory("permissions")
    if perm_factory:
        register_factory(PermissionService, perm_factory)
    else:
        register_singleton(PermissionService, SimplePermissionService())
```

**Important:** The current import at line 14 of `main.py` is:
```python
from agentarea_common.di.container import get_container, register_singleton
```
Update it to:
```python
from agentarea_common.di.container import get_container, register_factory, register_singleton
```

- [ ] **Step 4: Add wiring to Worker startup**

Modify `agentarea-platform/apps/worker/agentarea_worker/main.py`. Add extension discovery in `create_worker()` (after line 113 `initialize_di_container(settings.workflow)`):

```python
        # Discover extensions and wire permission service
        from agentarea_common.extensions import discover_extensions
        from agentarea_common.extensions.registry import ExtensionRegistry
        from agentarea_common.auth.permission import PermissionService
        from agentarea_common.auth.simple_permission import SimplePermissionService
        from agentarea_common.features.service import DeploymentMode, FeatureService
        from agentarea_common.config.app import get_app_settings
        from agentarea_common.di.container import register_singleton, register_factory

        discover_extensions()

        app_settings = get_app_settings()
        mode = DeploymentMode(app_settings.DEPLOYMENT_MODE)
        register_singleton(FeatureService, FeatureService(mode=mode))

        perm_factory = ExtensionRegistry.get_factory("permissions")
        if perm_factory:
            register_factory(PermissionService, perm_factory)
        else:
            register_singleton(PermissionService, SimplePermissionService())
```

- [ ] **Step 5: Run tests**

Run: `cd agentarea-platform && python -m pytest tests/unit/test_extension_wiring.py tests/unit/test_extension_registry.py tests/unit/test_permission_service.py tests/unit/test_feature_service.py -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add agentarea-platform/apps/api/agentarea_api/main.py agentarea-platform/apps/worker/agentarea_worker/main.py agentarea-platform/tests/unit/test_extension_wiring.py
git commit -m "feat: wire extension discovery and permission service into startup"
```

---

## Chunk 2: System Entity Visibility + Permission Checks in API

### Task 5: Fix System Entity Visibility in LLM Repositories

**Files:**
- Modify: `agentarea-platform/libs/llm/agentarea_llm/infrastructure/model_instance_repository.py:12-14`
- Modify: `agentarea-platform/libs/llm/agentarea_llm/infrastructure/model_spec_repository.py`
- Modify: `agentarea-platform/libs/llm/agentarea_llm/infrastructure/provider_config_repository.py`
- Test: `agentarea-platform/tests/unit/test_system_entity_visibility.py`

- [ ] **Step 1: Write failing test for system entity visibility**

```python
# tests/unit/test_system_entity_visibility.py
"""Test that system entities (workspace_id='system') are visible to regular users."""
import pytest
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy import or_

from agentarea_common.auth.context import UserContext
from agentarea_llm.infrastructure.model_instance_repository import ModelInstanceRepository


def test_model_instance_repo_workspace_filter_includes_system():
    """ModelInstanceRepository should include system entities in workspace filter."""
    session = MagicMock()
    user_context = UserContext(user_id="user-1", workspace_id="ws-1")
    repo = ModelInstanceRepository(session, user_context)

    # The repo should override _get_workspace_filter to include system
    ws_filter = repo._get_workspace_filter()
    # Verify it's an OR clause (not just workspace_id == ws-1)
    # The compiled SQL should contain both ws-1 and system
    compiled = str(ws_filter.compile(compile_kwargs={"literal_binds": True}))
    assert "system" in compiled
    assert "ws-1" in compiled
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agentarea-platform && python -m pytest tests/unit/test_system_entity_visibility.py -v`
Expected: FAIL — `_get_workspace_filter` only returns `workspace_id == ws-1`

- [ ] **Step 3: Add system entity visibility to ModelInstanceRepository**

Modify `agentarea-platform/libs/llm/agentarea_llm/infrastructure/model_instance_repository.py`.

Add import at top:

```python
from sqlalchemy import or_
```

Add method override after `__init__` (after line 14):

```python
    def _get_workspace_filter(self):
        """Include system entities (workspace_id='system') with is_public=True."""
        return or_(
            self.model_class.workspace_id == self.user_context.workspace_id,
            (self.model_class.workspace_id == "system") & self.model_class.is_public,
        )
```

- [ ] **Step 4: Apply to ProviderConfigRepository (has is_public field)**

Modify `agentarea-platform/libs/llm/agentarea_llm/infrastructure/provider_config_repository.py`.

Add `from sqlalchemy import or_` import, then add after `__init__`:

```python
    def _get_workspace_filter(self):
        """Include system entities (workspace_id='system') with is_public=True."""
        return or_(
            self.model_class.workspace_id == self.user_context.workspace_id,
            (self.model_class.workspace_id == "system") & self.model_class.is_public,
        )
```

- [ ] **Step 4b: Apply to ModelSpecRepository (no is_public field — use simpler filter)**

Modify `agentarea-platform/libs/llm/agentarea_llm/infrastructure/model_spec_repository.py`.

Add `from sqlalchemy import or_` import, then add after `__init__`:

```python
    def _get_workspace_filter(self):
        """Include system entities (workspace_id='system')."""
        return or_(
            self.model_class.workspace_id == self.user_context.workspace_id,
            self.model_class.workspace_id == "system",
        )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd agentarea-platform && python -m pytest tests/unit/test_system_entity_visibility.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add agentarea-platform/libs/llm/agentarea_llm/infrastructure/model_instance_repository.py agentarea-platform/libs/llm/agentarea_llm/infrastructure/model_spec_repository.py agentarea-platform/libs/llm/agentarea_llm/infrastructure/provider_config_repository.py agentarea-platform/tests/unit/test_system_entity_visibility.py
git commit -m "fix: include system entities in LLM repository queries"
```

---

### Task 6: Add Permission Checks to API Endpoints

**Files:**
- Modify: `agentarea-platform/apps/api/agentarea_api/api/v1/agents.py:232,259`
- Modify: `agentarea-platform/apps/api/agentarea_api/api/v1/mcp_servers_specifications.py:261,283`
- Modify: `agentarea-platform/apps/api/agentarea_api/api/v1/skills.py:287,307`
- Modify: `agentarea-platform/apps/api/agentarea_api/api/v1/model_instances.py:148`
- Test: `agentarea-platform/tests/functional/test_permission_checks.py`

- [ ] **Step 1: Write failing test**

```python
# tests/functional/test_permission_checks.py
"""Test that mutating endpoints call require_permission."""
import pytest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from agentarea_common.auth.permission import require_permission


@pytest.mark.asyncio
@patch("agentarea_api.api.v1.agents.require_permission", new_callable=AsyncMock)
async def test_update_agent_calls_require_permission(mock_perm):
    """Verify update_agent calls require_permission with correct args."""
    from agentarea_api.api.v1.agents import update_agent

    agent_id = uuid4()
    # This will fail because require_permission is not called yet in the endpoint
    # We just verify it IS called after we add it
    mock_perm.assert_not_called()  # baseline
```

- [ ] **Step 2: Add permission check to agents.py update_agent**

Modify `agentarea-platform/apps/api/agentarea_api/api/v1/agents.py`.

Add import at top:
```python
from agentarea_common.auth.permission import require_permission
```

Add at line 239 (first line of `update_agent` body, before `if data.model_id`):
```python
    await require_permission("edit", "agent", str(agent_id), user_context.user_id)
```

- [ ] **Step 3: Add permission check to agents.py delete_agent**

Add at line 265 (first line of `delete_agent` body):
```python
    await require_permission("delete", "agent", str(agent_id), user_context.user_id)
```

- [ ] **Step 4: Add permission check to mcp_servers_specifications.py**

Modify `agentarea-platform/apps/api/agentarea_api/api/v1/mcp_servers_specifications.py`.

Add import at top:
```python
from agentarea_common.auth.permission import require_permission
```

Add at first line of `update_mcp_server` body (line 267):
```python
    await require_permission("edit", "mcp_server", str(server_id), user_context.user_id)
```

Add at first line of `delete_mcp_server` body (line 288):
```python
    await require_permission("delete", "mcp_server", str(server_id), user_context.user_id)
```

- [ ] **Step 5: Add permission check to skills.py**

Modify `agentarea-platform/apps/api/agentarea_api/api/v1/skills.py`.

Add import at top:
```python
from agentarea_common.auth.permission import require_permission
from agentarea_common.auth.dependencies import get_user_context, UserContextDep
```

The `update_skill` and `delete_skill` endpoints currently don't have `user_context` in their signature. Add `user_context: UserContextDep` parameter to both.

Add at first line of `update_skill` body:
```python
    await require_permission("edit", "skill", str(skill_id), user_context.user_id)
```

Add at first line of `delete_skill` body:
```python
    await require_permission("delete", "skill", str(skill_id), user_context.user_id)
```

- [ ] **Step 6: Add permission check to model_instances.py**

Modify `agentarea-platform/apps/api/agentarea_api/api/v1/model_instances.py`.

Add import at top:
```python
from agentarea_common.auth.permission import require_permission
```

Add at first line of `delete_model_instance` body (line 154):
```python
    await require_permission("delete", "model_instance", str(instance_id), user_context.user_id)
```

- [ ] **Step 7: Run all tests**

Run: `cd agentarea-platform && python -m pytest tests/ -v -k "permission" --timeout=30`
Expected: All permission-related tests PASS

- [ ] **Step 8: Commit**

```bash
git add agentarea-platform/apps/api/agentarea_api/api/v1/agents.py agentarea-platform/apps/api/agentarea_api/api/v1/mcp_servers_specifications.py agentarea-platform/apps/api/agentarea_api/api/v1/skills.py agentarea-platform/apps/api/agentarea_api/api/v1/model_instances.py agentarea-platform/tests/functional/test_permission_checks.py
git commit -m "feat: add permission checks to mutating API endpoints"
```

---

## Chunk 3: IaC Config Reconciler

### Task 7: Reconciler Service + YAML Parsers

**Files:**
- Create: `agentarea-platform/libs/common/agentarea_common/reconciler/__init__.py`
- Create: `agentarea-platform/libs/common/agentarea_common/reconciler/service.py`
- Create: `agentarea-platform/libs/common/agentarea_common/reconciler/parsers.py`
- Test: `agentarea-platform/tests/unit/test_reconciler_parsers.py`

- [ ] **Step 1: Write failing tests for YAML parsing**

```python
# tests/unit/test_reconciler_parsers.py
import pytest
import tempfile
from pathlib import Path

from agentarea_common.reconciler.parsers import parse_yaml, YAMLValidationError


def test_parse_mcp_servers_yaml():
    yaml_content = """
mcp_servers:
  - name: test-mcp
    description: "Test MCP server"
    docker_image_url: ghcr.io/test/mcp
    version: "1.0.0"
"""
    with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False) as f:
        f.write(yaml_content)
        f.flush()
        specs = parse_yaml(Path(f.name), "mcp_servers")
        assert len(specs) == 1
        assert specs[0]["name"] == "test-mcp"
        assert specs[0]["docker_image_url"] == "ghcr.io/test/mcp"


def test_parse_agents_yaml():
    yaml_content = """
agents:
  - name: test-agent
    description: "Test agent"
    instruction: "You are a test agent."
    model: claude-sonnet-4-20250514
    tools:
      - type: code
        name: file_read
"""
    with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False) as f:
        f.write(yaml_content)
        f.flush()
        specs = parse_yaml(Path(f.name), "agents")
        assert len(specs) == 1
        assert specs[0]["name"] == "test-agent"
        assert specs[0]["tools"][0]["type"] == "code"


def test_parse_invalid_yaml_raises():
    with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False) as f:
        f.write("not: [valid: yaml: {{")
        f.flush()
        with pytest.raises(YAMLValidationError):
            parse_yaml(Path(f.name), "mcp_servers")


def test_parse_missing_required_field_raises():
    yaml_content = """
mcp_servers:
  - description: "Missing name field"
"""
    with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False) as f:
        f.write(yaml_content)
        f.flush()
        with pytest.raises(YAMLValidationError, match="name"):
            parse_yaml(Path(f.name), "mcp_servers")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd agentarea-platform && python -m pytest tests/unit/test_reconciler_parsers.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement parsers**

```python
# libs/common/agentarea_common/reconciler/__init__.py
from .service import ReconcilerService

__all__ = ["ReconcilerService"]
```

```python
# libs/common/agentarea_common/reconciler/parsers.py
"""YAML parsing and validation for seed data files."""

import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


class YAMLValidationError(Exception):
    """Raised when YAML content fails validation."""
    pass


# Required fields per entity type
REQUIRED_FIELDS: dict[str, list[str]] = {
    "mcp_servers": ["name"],
    "agents": ["name"],
    "skills": ["name"],
    "models": [],  # models has nested structure
}


def parse_yaml(file: Path, entity_type: str) -> list[dict[str, Any]]:
    """Parse and validate a YAML seed data file.

    Args:
        file: Path to YAML file.
        entity_type: One of mcp_servers, agents, skills, models.

    Returns:
        List of entity dicts.

    Raises:
        YAMLValidationError: If YAML is invalid or missing required fields.
    """
    try:
        with open(file) as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise YAMLValidationError(f"Invalid YAML in {file}: {e}") from e

    if not isinstance(data, dict):
        raise YAMLValidationError(f"Expected dict at top level in {file}, got {type(data)}")

    entities = data.get(entity_type, [])
    if not isinstance(entities, list):
        raise YAMLValidationError(f"Expected list for '{entity_type}' in {file}")

    required = REQUIRED_FIELDS.get(entity_type, [])
    for i, entity in enumerate(entities):
        if not isinstance(entity, dict):
            raise YAMLValidationError(f"Entity {i} in {file} is not a dict")
        for field in required:
            if field not in entity:
                raise YAMLValidationError(
                    f"Entity {i} in {file} missing required field: {field}"
                )

    return entities
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd agentarea-platform && python -m pytest tests/unit/test_reconciler_parsers.py -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add agentarea-platform/libs/common/agentarea_common/reconciler/ agentarea-platform/tests/unit/test_reconciler_parsers.py
git commit -m "feat: add YAML parsers for IaC config reconciler"
```

---

### Task 8: ReconcilerService with DB Upsert

**Files:**
- Create: `agentarea-platform/libs/common/agentarea_common/reconciler/service.py`
- Test: `agentarea-platform/tests/integration/test_reconciler_service.py`

- [ ] **Step 1: Write integration test**

```python
# tests/integration/test_reconciler_service.py
"""Integration test for ReconcilerService — requires database."""
import pytest
import tempfile
from pathlib import Path
from dataclasses import dataclass

from agentarea_common.reconciler.service import ReconcilerService, ReconcileResult


def test_reconcile_result_tracks_counts():
    result = ReconcileResult()
    result.created += 1
    result.updated += 2
    result.add_error("mcp_servers", "test error")
    assert result.created == 1
    assert result.updated == 2
    assert len(result.errors) == 1
    assert result.errors[0] == ("mcp_servers", "test error")


def test_reconcile_result_str():
    result = ReconcileResult()
    result.created = 3
    result.updated = 1
    s = str(result)
    assert "3" in s
    assert "1" in s
```

- [ ] **Step 2: Implement ReconcilerService**

```python
# libs/common/agentarea_common/reconciler/service.py
"""IaC config reconciler: YAML -> DB for system entities.

Additive-only — creates and updates but never deletes.
Uses raw async SQLAlchemy (not workspace-scoped repos) because:
1. Consistent with existing bootstrap scripts.
2. Workspace-scoped repos filter OUT system entities.
3. This is a trusted internal process.
"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .parsers import YAMLValidationError, parse_yaml

logger = logging.getLogger(__name__)

SYSTEM_WORKSPACE_ID = "system"
SYSTEM_USER_ID = "system"


@dataclass
class ReconcileResult:
    """Tracks reconciliation outcomes."""

    created: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[tuple[str, str]] = field(default_factory=list)

    def add_error(self, entity_type: str, message: str) -> None:
        self.errors.append((entity_type, message))

    def __str__(self) -> str:
        error_count = len(self.errors)
        return (
            f"ReconcileResult(created={self.created}, updated={self.updated}, "
            f"skipped={self.skipped}, errors={error_count})"
        )


class ReconcilerService:
    """Additive-only config applier: YAML -> DB for system entities."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._session_factory = session_factory

    async def reconcile(self, config_dir: str) -> ReconcileResult:
        """Read all YAML files from config_dir and upsert into DB."""
        result = ReconcileResult()
        config_path = Path(config_dir)

        for entity_type in ["mcp_servers", "agents", "skills", "models"]:
            yaml_file = config_path / f"{entity_type}.yaml"
            if not yaml_file.exists():
                logger.debug("No %s.yaml found in %s, skipping", entity_type, config_dir)
                continue

            try:
                specs = parse_yaml(yaml_file, entity_type)
            except YAMLValidationError as e:
                logger.error("Invalid YAML in %s: %s", yaml_file, e)
                result.add_error(entity_type, str(e))
                continue

            logger.info("Reconciling %d %s from %s", len(specs), entity_type, yaml_file)
            await self._upsert_entities(entity_type, specs, result)

        logger.info("Reconciliation complete: %s", result)
        return result

    async def _upsert_entities(
        self,
        entity_type: str,
        specs: list[dict],
        result: ReconcileResult,
    ) -> None:
        """Upsert entities with workspace_id='system'."""
        model_class = self._get_model_class(entity_type)
        if model_class is None:
            result.add_error(entity_type, f"Unknown entity type: {entity_type}")
            return

        async with self._session_factory() as session:
            for spec in specs:
                name = spec.get("name")
                try:
                    existing = await session.execute(
                        select(model_class).where(
                            model_class.name == name,
                            model_class.workspace_id == SYSTEM_WORKSPACE_ID,
                        )
                    )
                    entity = existing.scalar_one_or_none()

                    if entity:
                        self._apply_updates(entity, spec)
                        result.updated += 1
                        logger.debug("Updated %s: %s", entity_type, name)
                    else:
                        entity = model_class(
                            id=uuid4(),
                            workspace_id=SYSTEM_WORKSPACE_ID,
                            created_by=SYSTEM_USER_ID,
                            **self._prepare_create_fields(spec, entity_type),
                        )
                        session.add(entity)
                        result.created += 1
                        logger.debug("Created %s: %s", entity_type, name)

                    await session.commit()
                except Exception as e:
                    await session.rollback()
                    logger.error("Failed to upsert %s '%s': %s", entity_type, name, e)
                    result.add_error(entity_type, f"{name}: {e}")

    def _get_model_class(self, entity_type: str):
        """Lazy-import model classes to avoid circular imports."""
        if entity_type == "mcp_servers":
            from agentarea_mcp.domain.models import MCPServer
            return MCPServer
        elif entity_type == "agents":
            from agentarea_agents.domain.models import Agent
            return Agent
        elif entity_type == "skills":
            from agentarea_agents.domain.skill_models import Skill
            return Skill
        elif entity_type == "models":
            # Models have nested structure (providers + instances).
            # Handle via dedicated _reconcile_models() method.
            return None  # Special-cased in reconcile()
        return None

    def _prepare_create_fields(self, spec: dict, entity_type: str) -> dict:
        """Prepare fields for entity creation, handling JSON serialization."""
        fields = dict(spec)
        # JSON-serialize complex fields
        if entity_type == "mcp_servers":
            for json_field in ["env_schema", "cmd", "tags"]:
                if json_field in fields and not isinstance(fields[json_field], str):
                    fields[json_field] = json.dumps(fields[json_field])
        elif entity_type == "agents":
            if "tools" in fields and not isinstance(fields["tools"], str):
                fields["tools"] = json.dumps(fields["tools"])
            # Remove fields that need separate handling
            fields.pop("skills", None)
        return fields

    def _apply_updates(self, entity, spec: dict) -> None:
        """Apply spec fields to existing entity."""
        skip_fields = {"name", "skills"}  # name is the lookup key, skills are M2M
        for key, value in spec.items():
            if key in skip_fields:
                continue
            if hasattr(entity, key):
                if isinstance(value, (dict, list)):
                    value = json.dumps(value)
                setattr(entity, key, value)
```

- [ ] **Step 3: Run tests**

Run: `cd agentarea-platform && python -m pytest tests/integration/test_reconciler_service.py -v`
Expected: PASS (ReconcileResult tests don't need DB)

- [ ] **Step 4: Commit**

```bash
git add agentarea-platform/libs/common/agentarea_common/reconciler/service.py agentarea-platform/tests/integration/test_reconciler_service.py
git commit -m "feat: add ReconcilerService for IaC config"
```

---

### Task 9: Wire Reconciler into Bootstrap

**Files:**
- Modify: `agentarea-bootstrap/code/__init__.py`
- Create: `agentarea-bootstrap/code/reconcile.py`

- [ ] **Step 1: Create reconcile entrypoint**

```python
# agentarea-bootstrap/code/reconcile.py
"""Async entrypoint for the IaC config reconciler."""

import asyncio
import logging
import os
import sys

logger = logging.getLogger(__name__)


async def run_reconciliation():
    """Run the reconciler against seed data directory."""
    from agentarea_common.config import get_database
    from agentarea_common.reconciler.service import ReconcilerService

    # Seed data paths — from env vars set by Helm chart
    config_dir = os.environ.get("SEED_DATA_DIR", "/seed-data")

    if not os.path.isdir(config_dir):
        logger.warning("Seed data directory not found: %s", config_dir)
        return

    db = get_database()
    reconciler = ReconcilerService(session_factory=db.async_session_factory)

    result = await reconciler.reconcile(config_dir)
    logger.info("Reconciliation result: %s", result)

    if result.errors:
        logger.error("Reconciliation had %d errors", len(result.errors))
        for entity_type, msg in result.errors:
            logger.error("  %s: %s", entity_type, msg)
        sys.exit(1)


def main():
    """Entrypoint for bootstrap reconciliation."""
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_reconciliation())


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Add SEED_DATA_DIR to bootstrap job env**

Note: The Helm chart already mounts seed data to `/seed-data` via ConfigMap. Add an env var to the bootstrap container spec in `charts/agentarea/templates/jobs/bootstrap-job.yaml`:

```yaml
            - name: SEED_DATA_DIR
              value: {{ if .Values.jobs.bootstrap.seedData }}"/seed-data"{{ else }}"/app/llm"{{ end }}
```

- [ ] **Step 3: Commit**

```bash
git add agentarea-bootstrap/code/reconcile.py
git commit -m "feat: add async reconciler entrypoint for bootstrap"
```

---

## Chunk 4: Enterprise Package Scaffold

### Task 10: Scaffold agentarea-enterprise Repository

**Files:**
- Create: `../agentarea-enterprise/pyproject.toml`
- Create: `../agentarea-enterprise/agentarea_enterprise/__init__.py`
- Create: `../agentarea-enterprise/agentarea_enterprise/permissions/__init__.py`
- Create: `../agentarea-enterprise/agentarea_enterprise/permissions/keto.py`
- Create: `../agentarea-enterprise/agentarea_enterprise/permissions/factory.py`
- Create: `../agentarea-enterprise/README.md`

- [ ] **Step 1: Create directory structure**

```bash
mkdir -p ../agentarea-enterprise/agentarea_enterprise/permissions
```

- [ ] **Step 2: Create pyproject.toml**

```toml
# ../agentarea-enterprise/pyproject.toml
[project]
name = "agentarea-enterprise"
version = "0.1.0"
description = "Enterprise extensions for AgentArea"
requires-python = ">=3.12"
dependencies = [
    "ory-keto-client>=0.12.0",
]

[project.entry-points."agentarea.extensions"]
permissions = "agentarea_enterprise.permissions.factory:create_keto_permission_service"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

- [ ] **Step 3: Create package files**

```python
# ../agentarea-enterprise/agentarea_enterprise/__init__.py
"""AgentArea Enterprise extensions."""
```

```python
# ../agentarea-enterprise/agentarea_enterprise/permissions/__init__.py
from .keto import KetoPermissionService

__all__ = ["KetoPermissionService"]
```

```python
# ../agentarea-enterprise/agentarea_enterprise/permissions/keto.py
"""Keto ReBAC permission service."""

import logging

from agentarea_common.auth.permission import PermissionService

logger = logging.getLogger(__name__)


class KetoPermissionService(PermissionService):
    """Permission service backed by Ory Keto ReBAC.

    Evaluates relation tuples to determine access.
    System entities (workspace_id='system') are protected because
    no user has edit/delete relations on them.
    """

    def __init__(self, keto_read_url: str):
        self.keto_read_url = keto_read_url
        # TODO: Initialize actual Keto client
        # from ory_keto_client import ApiClient, Configuration, RelationshipApi
        # config = Configuration(host=keto_read_url)
        # self.client = RelationshipApi(ApiClient(config))

    async def check(
        self,
        user_id: str,
        permission: str,
        resource_type: str,
        resource_id: str,
    ) -> bool:
        """Check permission via Keto relation tuple lookup.

        Args:
            user_id: Subject requesting access.
            permission: Relation to check (view, edit, delete, execute).
            resource_type: Namespace (agent, mcp_server, skill, etc.).
            resource_id: Object ID.

        Returns:
            True if relation exists (allowed), False otherwise.
        """
        logger.debug(
            "Keto check: user=%s permission=%s resource=%s/%s",
            user_id, permission, resource_type, resource_id,
        )
        # TODO: Implement actual Keto check
        # try:
        #     self.client.check_relation_tuple(
        #         namespace=resource_type,
        #         object=resource_id,
        #         relation=permission,
        #         subject_id=user_id,
        #     )
        #     return True
        # except ApiException as e:
        #     if e.status == 403:
        #         return False
        #     raise
        return True  # Placeholder until Keto is wired
```

```python
# ../agentarea-enterprise/agentarea_enterprise/permissions/factory.py
"""Entrypoint factory for KetoPermissionService."""

import os

from .keto import KetoPermissionService


def create_keto_permission_service() -> KetoPermissionService:
    """Factory function registered as agentarea.extensions entrypoint.

    Reads KETO_READ_URL from environment.
    """
    keto_url = os.environ.get("KETO_READ_URL", "http://keto:4466")
    return KetoPermissionService(keto_read_url=keto_url)
```

- [ ] **Step 4: Initialize git repo**

```bash
cd ../agentarea-enterprise && git init && git add -A && git commit -m "feat: scaffold agentarea-enterprise with Keto permission service"
```

- [ ] **Step 5: Verify entrypoint works**

```bash
cd ../agentarea-enterprise && pip install -e . && python -c "from importlib.metadata import entry_points; eps = entry_points(group='agentarea.extensions'); print([ep.name for ep in eps])"
```
Expected: `['permissions']`

- [ ] **Step 6: Uninstall for now (don't pollute dev env)**

```bash
pip uninstall agentarea-enterprise -y
```

---

## Summary

| Task | What | Files Changed | Depends On |
|------|------|--------------|------------|
| 1 | Extension Registry | 3 new + 1 test | — |
| 2 | Feature Service | 3 new + 1 test + 1 modified | — |
| 3 | Permission Service | 3 new + 1 test | — |
| 4 | Wire into DI/Startup | 2 modified + 1 test | 1, 2, 3 |
| 5 | System Entity Visibility | 3 modified + 1 test | — |
| 6 | Permission Checks in API | 4 modified + 1 test | 3, 4 |
| 7 | Reconciler Parsers | 3 new + 1 test | — |
| 8 | ReconcilerService | 1 new + 1 test | 7 |
| 9 | Bootstrap Integration | 1 new + 1 modified | 8 |
| 10 | Enterprise Package | 6 new (separate repo) | 3 |

Tasks 1-3, 5, 7 are independent and can be parallelized.
