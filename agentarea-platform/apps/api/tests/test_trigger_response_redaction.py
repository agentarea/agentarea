"""A webhook's signing secret is write-only: no trigger response carries it."""

from types import SimpleNamespace
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
from agentarea_triggers.domain.models import WebhookTrigger
from agentarea_triggers.webhook_verification import REDACTED_SECRET
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

SIGNING_SECRET = "whsec_do_not_echo"  # noqa: S105  # pragma: allowlist secret
BOT_TOKEN = "123456:bot-token-do-not-echo"  # noqa: S105  # pragma: allowlist secret


@pytest.fixture(autouse=True)
def _graph_ownership(monkeypatch):
    allow_all_permissions()
    return install_graph_ownership_stub(monkeypatch)


@pytest.fixture
def harness():
    trigger = WebhookTrigger(
        id=uuid4(),
        name="Stripe payments",
        agent_id=uuid4(),
        created_by="user-a",
        webhook_id="stripe-hook",
        webhook_type="stripe",
        validation_rules={"signing_secret": SIGNING_SECRET, "required_headers": ["x-a"]},
        webhook_config={"bot_token": BOT_TOKEN, "field_map": {"text": "data.object.id"}},
    )
    service = AsyncMock()
    service.get_trigger.return_value = trigger
    service.list_triggers.return_value = [trigger]
    service.create_trigger.return_value = trigger
    service.update_trigger.return_value = trigger
    manager = AsyncMock(spec=BaseSecretManager)
    manager.has_secret.return_value = False
    app = FastAPI()
    app.include_router(triggers.router, prefix="/v1")
    app.dependency_overrides[get_user_context] = lambda: UserContext(
        user_id="user-a", workspace_id="workspace-a"
    )
    app.dependency_overrides[get_trigger_service] = lambda: service
    app.dependency_overrides[get_secret_manager] = lambda: manager
    app.dependency_overrides[get_secret_catalog_service] = lambda: AsyncMock(
        spec=SecretCatalogService
    )
    app.dependency_overrides[triggers.get_channel_webhook_service] = lambda: AsyncMock()
    return SimpleNamespace(app=app, trigger=trigger)


async def _call(harness, operation):
    async with AsyncClient(
        transport=ASGITransport(app=harness.app), base_url="http://test"
    ) as client:
        if operation == "get":
            return await client.get(f"/v1/triggers/{harness.trigger.id}")
        if operation == "list":
            return await client.get("/v1/triggers/")
        if operation == "update":
            return await client.put(f"/v1/triggers/{harness.trigger.id}", json={"name": "x"})
        return await client.post(
            "/v1/triggers/",
            json={
                "name": "Stripe payments",
                "agent_id": str(harness.trigger.agent_id),
                "trigger_type": "webhook",
                "webhook_type": "stripe",
                "validation_rules": {"signing_secret": SIGNING_SECRET},
            },
        )


@pytest.mark.parametrize("operation", ["get", "list", "update", "create"])
async def test_no_trigger_response_carries_a_signing_secret(harness, operation):
    response = await _call(harness, operation)

    assert response.status_code in (200, 201), response.text
    assert SIGNING_SECRET not in response.text
    assert BOT_TOKEN not in response.text

    body = response.json()
    trigger = body[0] if isinstance(body, list) else body
    # Configured, and visibly so; the non-secret settings are untouched.
    assert trigger["validation_rules"]["signing_secret"] == REDACTED_SECRET
    assert trigger["validation_rules"]["required_headers"] == ["x-a"]
    assert trigger["webhook_config"]["bot_token"] == REDACTED_SECRET
    assert trigger["webhook_config"]["field_map"] == {"text": "data.object.id"}
