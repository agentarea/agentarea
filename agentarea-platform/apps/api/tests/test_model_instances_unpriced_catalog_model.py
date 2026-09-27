"""A catalog model without a price is refused with 422, one bulk item at a time.

Runs bill at the model's price, so a model without one would only fail later,
at run time. The bulk endpoint reports it as that item's failure and keeps the
rest of the batch, as it does for an unknown spec.
"""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from agentarea_api.api.deps.services import get_provider_service
from agentarea_api.api.v1.model_instances import router
from agentarea_common.auth.authorization import AuthorizationService
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.dependencies import get_user_context
from agentarea_common.auth.workspace_authorization import WorkspaceScopedAuthorizationService
from agentarea_common.di.container import register_singleton
from agentarea_common.exceptions.registration import register_error_handlers
from agentarea_llm.infrastructure.model_spec_repository import ModelPricingNotConfiguredError
from fastapi import FastAPI
from fastapi.testclient import TestClient

MEMBER = UserContext(user_id="user-member", workspace_id="ws-acme", admin_workspaces=[])
UNPRICED = uuid4()


@pytest.fixture(autouse=True)
def _authz():
    register_singleton(AuthorizationService, WorkspaceScopedAuthorizationService())


def _instance():
    instance = MagicMock()
    instance.id = uuid4()
    instance.provider_config = None
    instance.model_spec = None
    instance.is_active = True
    instance.is_public = False
    instance.name = "priced"
    instance.description = None
    instance.provider_config_id = uuid4()
    instance.model_spec_id = uuid4()
    instance.created_at = "2026-01-01T00:00:00Z"
    instance.updated_at = "2026-01-01T00:00:00Z"
    return instance


async def _create(*, model_spec_id, **_):
    if model_spec_id == UNPRICED:
        raise ModelPricingNotConfiguredError("Model has no price")
    return _instance()


@pytest.fixture
def client() -> TestClient:
    service = MagicMock()
    service.create_model_instance = AsyncMock(side_effect=_create)
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(router, prefix="/v1/workspaces/{workspace}")
    app.dependency_overrides[get_provider_service] = lambda: service
    app.dependency_overrides[get_user_context] = lambda: MEMBER
    return TestClient(app)


def _item(model_spec_id):
    return {"provider_config_id": str(uuid4()), "model_spec_id": str(model_spec_id), "name": "m"}


def test_adding_an_unpriced_catalog_model_answers_422(client):
    resp = client.post("/v1/workspaces/ws-acme/model-instances/", json=_item(UNPRICED))

    assert resp.status_code == 422
    assert resp.json()["detail"] == "Model has no price"


def test_bulk_reports_an_unpriced_model_as_that_items_failure(client):
    resp = client.post(
        "/v1/workspaces/ws-acme/model-instances/bulk",
        json={"items": [_item(UNPRICED), _item(uuid4())]},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["succeeded_count"] == 1
    assert body["failed"] == [
        {"index": 0, "model_spec_id": str(UNPRICED), "error": "Model has no price"}
    ]
