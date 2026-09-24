"""Provider configurations hold the workspace's model API keys; writing one takes admin.

``POST/PUT/PATCH/DELETE /v1/provider-configs`` required workspace admin, while
``providers_create_config``/``update_config``/``delete_config`` over MCP reached
the same ``ProviderService`` methods with no check: any member could rotate the
key every agent in the workspace bills against. The check now lives in the
service, so every caller surface inherits it.
"""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from agentarea_common.auth.authorization import AuthorizationService
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.workspace_authorization import WorkspaceScopedAuthorizationService
from agentarea_common.di.container import get_container
from agentarea_llm.application.provider_service import ProviderService
from agentarea_llm.schemas.dto import ProviderConfigCreate, ProviderConfigUpdate
from fastapi import HTTPException

WORKSPACE = "ws-acme"
MEMBER = UserContext(user_id="user-member", workspace_id=WORKSPACE, admin_workspaces=[])
OWNER = UserContext(user_id="user-owner", workspace_id=WORKSPACE, admin_workspaces=[WORKSPACE])


@pytest.fixture(autouse=True)
def _authorization():
    container = get_container()
    saved = dict(container._singletons)
    container.register_singleton(AuthorizationService, WorkspaceScopedAuthorizationService())
    yield
    container._singletons.clear()
    container._singletons.update(saved)


def _service(user_context: UserContext) -> tuple[ProviderService, MagicMock, AsyncMock]:
    config_repo = MagicMock()
    config_repo.user_context = user_context
    config_repo.get_by_id = AsyncMock(return_value=None)
    config_repo.delete = AsyncMock(return_value=False)
    config_repo.session.execute = AsyncMock()
    secrets = AsyncMock()
    service = ProviderService(
        provider_spec_repo=MagicMock(),
        provider_config_repo=config_repo,
        model_spec_repo=MagicMock(),
        model_instance_repo=MagicMock(),
        event_broker=AsyncMock(),
        secret_manager=secrets,
    )
    return service, config_repo, secrets


WRITES = {
    "create": lambda s: s.create_provider_config(
        payload=ProviderConfigCreate(provider_spec_id=uuid4(), name="openai", api_key="sk-x"),
        created_by="someone",
    ),
    "update": lambda s: s.update_provider_config(
        config_id=uuid4(), payload=ProviderConfigUpdate(api_key="sk-y")
    ),
    "delete": lambda s: s.delete_provider_config(uuid4()),
}


@pytest.mark.asyncio
@pytest.mark.parametrize("write", WRITES.values(), ids=WRITES.keys())
async def test_a_member_cannot_write_a_provider_config(write) -> None:
    service, config_repo, secrets = _service(MEMBER)

    with pytest.raises(HTTPException) as refused:
        await write(service)

    assert refused.value.status_code == 403
    config_repo.get_by_id.assert_not_called()
    config_repo.delete.assert_not_called()
    secrets.set_secret.assert_not_called()


@pytest.mark.asyncio
async def test_an_admin_reaches_the_store() -> None:
    service, config_repo, _secrets = _service(OWNER)

    assert await service.update_provider_config(uuid4(), ProviderConfigUpdate(name="x")) is None
    assert await service.delete_provider_config(uuid4()) is False

    config_repo.get_by_id.assert_called()
    config_repo.delete.assert_called_once()
