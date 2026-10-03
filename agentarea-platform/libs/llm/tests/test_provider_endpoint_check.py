"""The endpoint check resolves DNS; it must not do so on the API's event loop.

``getaddrinfo`` blocks, and a slow or unreachable resolver used to stall every
request the loop was serving while one provider config was being saved.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from agentarea_common.auth.authorization import AuthorizationService
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.workspace_authorization import WorkspaceScopedAuthorizationService
from agentarea_common.di.container import get_container
from agentarea_common.exceptions.errors import BadRequestError
from agentarea_common.utils.url_safety import UnsafeUrlError
from agentarea_llm.application import provider_service
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


@pytest.mark.asyncio
async def test_endpoint_is_resolved_off_the_event_loop(monkeypatch) -> None:
    resolved_on_loop: list[bool] = []

    def refuse(url, **_kwargs):
        try:
            asyncio.get_running_loop()
            resolved_on_loop.append(True)
        except RuntimeError:
            resolved_on_loop.append(False)
        raise UnsafeUrlError(f"{url} resolves to non-public address 10.0.0.5")

    monkeypatch.setattr(provider_service, "validate_outbound_url", refuse)
    config_repo = MagicMock()
    config_repo.user_context = OWNER
    service = ProviderService(
        provider_spec_repo=MagicMock(),
        provider_config_repo=config_repo,
        model_spec_repo=MagicMock(),
        model_instance_repo=MagicMock(),
        event_broker=AsyncMock(),
        secret_manager=AsyncMock(),
    )

    with pytest.raises(BadRequestError):
        await service.create_provider_config(
            payload=ProviderConfigCreate(
                provider_spec_id=uuid4(), name="ollama", endpoint_url="http://ollama.lan:11434"
            ),
            created_by="user-owner",
        )

    assert resolved_on_loop == [False]
