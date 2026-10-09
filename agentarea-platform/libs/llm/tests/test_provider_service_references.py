"""A reference the workspace cannot see is the caller's mistake, not a database error.

Unknown provider-config, model-spec and secret ids used to reach the INSERT and
fail there as foreign-key violations, or escape as a bare ValueError: both
answered 500, and in the bulk model-instance route the failed flush poisoned
the session for every item after it.
"""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from agentarea_common.auth.authorization import AuthorizationService
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.workspace_authorization import WorkspaceScopedAuthorizationService
from agentarea_common.di.container import get_container
from agentarea_common.exceptions.errors import NotFoundError
from agentarea_llm.application.provider_service import ProviderService
from agentarea_llm.schemas.dto import ProviderConfigCreate

WORKSPACE = "ws-acme"
OWNER = UserContext(user_id="user-owner", workspace_id=WORKSPACE, admin_workspaces=[WORKSPACE])


@pytest.fixture(autouse=True)
def _authorization():
    container = get_container()
    saved = dict(container._singletons)
    container.register_singleton(AuthorizationService, WorkspaceScopedAuthorizationService())
    yield
    container._singletons.clear()
    container._singletons.update(saved)


def _service(
    *, config=None, spec=None, provider_spec=MagicMock()
) -> tuple[ProviderService, MagicMock]:
    provider_spec_repo = MagicMock()
    provider_spec_repo.get_by_id = AsyncMock(return_value=provider_spec)
    config_repo = MagicMock()
    config_repo.user_context = OWNER
    config_repo.get_by_id = AsyncMock(return_value=config)
    missing_secret = MagicMock()
    missing_secret.scalar_one_or_none.return_value = None
    config_repo.session.execute = AsyncMock(return_value=missing_secret)
    spec_repo = MagicMock()
    spec_repo.get_usable = AsyncMock(return_value=spec)
    spec_repo.get_or_copy_catalog_spec = AsyncMock(return_value=None)
    instance_repo = MagicMock()
    instance_repo.create_instance = AsyncMock()
    service = ProviderService(
        provider_spec_repo=provider_spec_repo,
        provider_config_repo=config_repo,
        model_spec_repo=spec_repo,
        model_instance_repo=instance_repo,
        event_broker=AsyncMock(),
        secret_manager=AsyncMock(),
    )
    return service, instance_repo


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("config", "spec"),
    [(None, MagicMock()), (MagicMock(), None)],
    ids=["unknown-provider-config", "unknown-model-spec"],
)
async def test_a_model_instance_needs_references_the_workspace_can_see(config, spec) -> None:
    service, instance_repo = _service(config=config, spec=spec)

    with pytest.raises(NotFoundError):
        await service.create_model_instance(
            provider_config_id=uuid4(), model_spec_id=uuid4(), name="gpt"
        )

    instance_repo.create_instance.assert_not_called()


@pytest.mark.asyncio
async def test_a_provider_config_cannot_borrow_a_secret_outside_the_workspace() -> None:
    service, _ = _service()

    with pytest.raises(NotFoundError):
        await service.create_provider_config(
            payload=ProviderConfigCreate(
                provider_spec_id=uuid4(), name="openai", api_key_secret_id=uuid4()
            ),
            created_by="user-owner",
        )


@pytest.mark.asyncio
async def test_an_unknown_provider_spec_writes_no_key() -> None:
    service, _ = _service(provider_spec=None)

    with pytest.raises(NotFoundError):
        await service.create_provider_config(
            payload=ProviderConfigCreate(provider_spec_id=uuid4(), name="openai", api_key="sk-1"),
            created_by="user-owner",
        )

    service.secret_manager.set_secret.assert_not_called()


@pytest.mark.asyncio
async def test_a_failed_insert_removes_the_key_it_stored() -> None:
    service, _ = _service()
    service.provider_config_repo.create_config = AsyncMock(side_effect=RuntimeError("insert"))

    with pytest.raises(RuntimeError):
        await service.create_provider_config(
            payload=ProviderConfigCreate(provider_spec_id=uuid4(), name="openai", api_key="sk-1"),
            created_by="user-owner",
        )

    (stored, _), _ = service.secret_manager.set_secret.call_args
    service.secret_manager.delete_secret.assert_awaited_once_with(stored)
