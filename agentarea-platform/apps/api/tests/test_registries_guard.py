"""ReBAC guard for global registry-catalog writes.

The registry catalog is global, platform-owned infrastructure (ADR-003). Writes
must be gated by the AuthorizationService (ReBAC), not by a role. A regular
workspace user must be rejected; the platform principal is allowed.
"""

import pytest
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.simple_authorization import SimpleAuthorizationService
from agentarea_common.constants import PLATFORM_WORKSPACE_ID
from agentarea_common.di.container import register_singleton
from agentarea_common.testing.flows import MainFlow
from fastapi import HTTPException


@pytest.fixture(autouse=True)
def _register_authz():
    from agentarea_common.auth.authorization import AuthorizationService

    register_singleton(AuthorizationService, SimpleAuthorizationService())


async def test_regular_user_cannot_write_catalog():
    from agentarea_api.api.v1.registries import require_platform_catalog_write

    ctx = UserContext(user_id="u1", workspace_id="ws-1")
    with pytest.raises(HTTPException) as exc:
        await require_platform_catalog_write(ctx)
    assert exc.value.status_code == 403


@pytest.mark.flow(MainFlow.REGISTRY_CATALOG)
async def test_platform_principal_can_write_catalog():
    from agentarea_api.api.v1.registries import require_platform_catalog_write

    ctx = UserContext(user_id="platform", workspace_id=PLATFORM_WORKSPACE_ID)
    # Should not raise.
    assert await require_platform_catalog_write(ctx) is None
