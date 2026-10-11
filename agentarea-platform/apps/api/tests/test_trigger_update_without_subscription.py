"""A trigger whose stream subscription is gone cannot have its filter changed: 409, not 500."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from agentarea_api.api.deps.services import (
    get_secret_catalog_service,
    get_secret_manager,
    get_trigger_service,
)
from agentarea_api.api.v1 import triggers
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.dependencies import get_user_context
from agentarea_common.infrastructure.secret_manager import BaseSecretManager
from agentarea_common.testing import allow_all_permissions, install_graph_ownership_stub
from agentarea_secrets.catalog_service import SecretCatalogService
from agentarea_streams.domain import TriggerSubscriptionNotFoundError
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


@pytest.fixture(autouse=True)
def _graph_ownership(monkeypatch):
    allow_all_permissions()
    return install_graph_ownership_stub(monkeypatch)


async def test_changing_the_filter_of_a_trigger_without_a_subscription_is_a_conflict():
    trigger_id = uuid4()
    service = AsyncMock()
    service.update_trigger.side_effect = TriggerSubscriptionNotFoundError(trigger_id)
    app = FastAPI()
    app.include_router(triggers.router, prefix="/v1/workspaces/{workspace}")
    app.dependency_overrides[get_user_context] = lambda: UserContext(
        user_id="user-a", workspace_id="workspace-a"
    )
    app.dependency_overrides[get_trigger_service] = lambda: service
    app.dependency_overrides[get_secret_manager] = lambda: AsyncMock(spec=BaseSecretManager)
    app.dependency_overrides[get_secret_catalog_service] = lambda: AsyncMock(
        spec=SecretCatalogService
    )
    app.dependency_overrides[triggers.get_channel_webhook_service] = lambda: AsyncMock()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.put(
            f"/v1/workspaces/workspace-a/triggers/{trigger_id}",
            json={"event_filter": {"kinds": ["x"]}},
        )
    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert str(trigger_id) in detail
    assert "Delete the trigger" in detail
