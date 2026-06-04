"""Tests for KetoPermissionService mapping generic checks onto Keto."""

from unittest.mock import AsyncMock

import pytest
from agentarea_common.auth.keto_permission import KetoPermissionService
from agentarea_common.rebac.keto_client import KetoError
from agentarea_common.rebac.models import CheckResult


def _svc(check_return=None, side_effect=None):
    keto = AsyncMock()
    if side_effect is not None:
        keto.check.side_effect = side_effect
    else:
        keto.check.return_value = CheckResult(allowed=check_return)
    return KetoPermissionService(keto), keto


@pytest.mark.asyncio
async def test_skill_use_maps_to_use_relation_and_user_subject():
    svc, keto = _svc(check_return=True)
    allowed = await svc.check("u1", "use", "skill", "copywriting")
    assert allowed is True
    keto.check.assert_awaited_once_with(
        namespace="Skill", object="copywriting", relation="use", subject_id="User:u1"
    )


@pytest.mark.asyncio
async def test_skill_edit_maps_to_configure():
    svc, keto = _svc(check_return=False)
    await svc.check("u1", "edit", "skill", "x")
    assert keto.check.await_args.kwargs["relation"] == "configure"


@pytest.mark.asyncio
async def test_mcp_view_maps_to_connect():
    svc, keto = _svc(check_return=True)
    await svc.check("u1", "view", "mcp_server", "github")
    assert keto.check.await_args.kwargs["namespace"] == "MCPServer"
    assert keto.check.await_args.kwargs["relation"] == "connect"


@pytest.mark.asyncio
async def test_agent_execute_maps_to_operate():
    svc, keto = _svc(check_return=True)
    await svc.check("u1", "execute", "agent", "support-bot")
    assert keto.check.await_args.kwargs["relation"] == "operate"


@pytest.mark.asyncio
async def test_unknown_resource_type_allows_without_calling_keto():
    svc, keto = _svc(check_return=False)
    allowed = await svc.check("u1", "view", "dashboard", "x")
    assert allowed is True
    keto.check.assert_not_awaited()


@pytest.mark.asyncio
async def test_unmapped_permission_denies():
    svc, keto = _svc(check_return=True)
    allowed = await svc.check("u1", "frobnicate", "skill", "x")
    assert allowed is False
    keto.check.assert_not_awaited()


@pytest.mark.asyncio
async def test_keto_error_fails_closed():
    svc, _ = _svc(side_effect=KetoError("down"))
    allowed = await svc.check("u1", "use", "skill", "x")
    assert allowed is False
