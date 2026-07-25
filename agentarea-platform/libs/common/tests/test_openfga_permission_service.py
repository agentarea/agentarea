"""Tests for OpenFGAPermissionService mapping generic checks onto OpenFGA."""

from unittest.mock import AsyncMock

import pytest
from agentarea_common.auth.openfga_permission import OpenFGAPermissionService
from agentarea_common.rebac.models import CheckResult
from agentarea_common.rebac.openfga_client import OpenFGAError


def _svc(check_return=None, side_effect=None):
    openfga = AsyncMock()
    if side_effect is not None:
        openfga.check.side_effect = side_effect
    else:
        openfga.check.return_value = CheckResult(allowed=check_return)
    return OpenFGAPermissionService(openfga), openfga


@pytest.mark.asyncio
async def test_skill_use_maps_to_resource_read_bit_and_user_subject():
    svc, openfga = _svc(check_return=True)
    allowed = await svc.check("u1", "use", "skill", "copywriting")
    assert allowed is True
    openfga.check.assert_awaited_once_with(
        namespace="resource", object="copywriting", relation="can_read", subject_id="User:u1"
    )


@pytest.mark.asyncio
async def test_mcp_view_maps_to_resource_read_bit():
    svc, openfga = _svc(check_return=True)
    await svc.check("u1", "view", "mcp_server", "github")
    assert openfga.check.await_args.kwargs["namespace"] == "resource"
    assert openfga.check.await_args.kwargs["relation"] == "can_read"


@pytest.mark.asyncio
async def test_ungoverned_resource_type_allows_without_calling_openfga():
    svc, openfga = _svc(check_return=False)
    allowed = await svc.check("u1", "view", "model_instance", "x")
    assert allowed is True
    openfga.check.assert_not_awaited()


@pytest.mark.asyncio
async def test_unmapped_permission_denies():
    svc, openfga = _svc(check_return=True)
    allowed = await svc.check("u1", "frobnicate", "skill", "x")
    assert allowed is False
    openfga.check.assert_not_awaited()


@pytest.mark.asyncio
async def test_openfga_error_propagates_to_fail_closed():
    svc, _ = _svc(side_effect=OpenFGAError("down"))
    # The service fails CLOSED by raising; the caller (require_permission) surfaces it.
    with pytest.raises(OpenFGAError):
        await svc.check("u1", "use", "skill", "x")
