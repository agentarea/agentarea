"""``require_permission`` is the enforcement point; the decision comes from the PDP.

The open-core ``WorkspaceScopedPermissionService`` this file used to exercise is
gone: it answered every check with True, so an absent authorization backend read
as permission granted. There is no fallback implementation any more -- startup
fails instead.
"""

from unittest.mock import AsyncMock

import pytest
from agentarea_common.auth.permission import PermissionService, require_permission
from agentarea_common.di.container import get_container
from fastapi import HTTPException


@pytest.fixture(autouse=True)
def clean_container():
    container = get_container()
    yield
    container.clear()


def _pdp(answer: bool) -> AsyncMock:
    svc = AsyncMock(spec=PermissionService)
    svc.check.return_value = answer
    return svc


@pytest.mark.asyncio
async def test_passes_when_the_pdp_allows():
    get_container().register_singleton(PermissionService, _pdp(True))

    await require_permission("edit", "agent", "agent-123", "user-1")


@pytest.mark.asyncio
async def test_raises_403_when_the_pdp_denies():
    get_container().register_singleton(PermissionService, _pdp(False))

    with pytest.raises(HTTPException) as error:
        await require_permission("edit", "agent", "agent-123", "user-1")

    assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_the_question_reaches_the_pdp_unchanged():
    """A gate that quietly rewrote the question would be worse than no gate."""
    pdp = _pdp(True)
    get_container().register_singleton(PermissionService, pdp)

    await require_permission("delete", "mcp_server", "mcp-7", "user-1")

    pdp.check.assert_awaited_once_with("user-1", "delete", "mcp_server", "mcp-7")


def test_permission_service_is_abstract():
    with pytest.raises(TypeError):
        PermissionService()
