"""Every route that writes a model spec's price answers 403 to a plain member.

Discovery persists what the provider reports, prices included, so it is a price
write like PATCH. The refusal comes before the provider is ever called.
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from agentarea_api.api.deps.services import get_model_spec_repository, get_provider_service
from agentarea_api.api.v1.model_specs import router as model_specs_router
from agentarea_api.api.v1.provider_configs import router as provider_configs_router
from agentarea_common.auth.authorization import AuthorizationService
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.dependencies import get_user_context
from agentarea_common.auth.workspace_authorization import WorkspaceScopedAuthorizationService
from agentarea_common.di.container import register_singleton
from fastapi import FastAPI
from fastapi.testclient import TestClient

MEMBER = UserContext(user_id="user-member", workspace_id="ws-acme", admin_workspaces=[])
SPEC = {
    "provider_spec_id": str(uuid4()),
    "model_name": "gpt-5",
    "display_name": "GPT-5",
    "context_window": 8192,
    "input_cost_per_token": 0.0,
    "output_cost_per_token": 0.0,
}


@pytest.fixture(autouse=True)
def _authz():
    register_singleton(AuthorizationService, WorkspaceScopedAuthorizationService())


@pytest.fixture
def repo() -> AsyncMock:
    repo = AsyncMock()
    repo.user_context = MEMBER
    return repo


@pytest.fixture
def client(repo) -> TestClient:
    app = FastAPI()
    app.include_router(model_specs_router, prefix="/v1")
    app.include_router(provider_configs_router, prefix="/v1")
    app.dependency_overrides[get_model_spec_repository] = lambda: repo
    app.dependency_overrides[get_provider_service] = lambda: MagicMock()
    app.dependency_overrides[get_user_context] = lambda: MEMBER
    return TestClient(app)


WRITES = {
    "create": ("post", "/v1/model-specs/", SPEC),
    "upsert": ("post", "/v1/model-specs/upsert", SPEC),
    "update": ("patch", f"/v1/model-specs/{uuid4()}", {"input_cost_per_token": 0.0}),
    "delete": ("delete", f"/v1/model-specs/{uuid4()}", None),
    "discover": ("post", f"/v1/provider-configs/{uuid4()}/discover", None),
    "discover-preview": (
        "post",
        "/v1/provider-configs/discover-preview",
        {"provider_key": "openai", "api_key": "sk-test"},  # pragma: allowlist secret
    ),
}


@pytest.mark.parametrize("write", WRITES.values(), ids=WRITES.keys())
def test_a_member_is_refused_before_anything_is_written(client, repo, write) -> None:
    method, path, body = write
    with patch(
        "agentarea_api.api.v1.provider_configs.ModelDiscoveryService.discover",
        new=AsyncMock(),
    ) as discover:
        response = client.request(method, path, json=body)

    assert response.status_code == 403, response.text
    discover.assert_not_awaited()
    for method_name in ("create", "update", "delete", "upsert_by_provider_and_model_kwargs"):
        getattr(repo, method_name).assert_not_awaited()
