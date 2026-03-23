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
