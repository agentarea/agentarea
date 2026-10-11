"""Creating an API key: a bounded name, and a failure that leaks nothing.

A 300-character name used to reach the ``String(255)`` column and come back as
a 500 whose detail was the exception text: the INSERT statement with its
parameters, the new key's ``token_hash`` among them. An empty name was stored.
"""

from unittest.mock import AsyncMock

import pytest
from agentarea_api.api.deps.services import get_audit_service, get_db_session
from agentarea_api.api.v1.api_keys import APIKeyCreateRequest, get_api_key_service, router
from agentarea_common.auth.authorization import AuthorizationService
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.dependencies import get_user_context
from agentarea_common.auth.workspace_authorization import WorkspaceScopedAuthorizationService
from agentarea_common.di.container import get_container
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

MEMBER = UserContext(user_id="user-member", workspace_id="ws-acme", admin_workspaces=[])
LEAKED = "INSERT INTO api_keys (token_hash) VALUES ('deadbeefcafe')"


@pytest.fixture(autouse=True)
def _authz():
    container = get_container()
    saved = dict(container._singletons)
    container.register_singleton(AuthorizationService, WorkspaceScopedAuthorizationService())
    yield
    container._singletons.clear()
    container._singletons.update(saved)


@pytest.mark.parametrize("name", ["", "x" * 256, "x" * 300], ids=["empty", "256", "300"])
def test_a_name_outside_one_to_255_characters_is_refused(name: str) -> None:
    with pytest.raises(ValidationError):
        APIKeyCreateRequest(name=name)


@pytest.mark.parametrize("name", ["x", "x" * 255], ids=["1", "255"])
def test_a_name_within_bounds_is_accepted(name: str) -> None:
    assert APIKeyCreateRequest(name=name).name == name


def _client(service: AsyncMock) -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/v1/workspaces/{workspace}")
    app.dependency_overrides[get_api_key_service] = lambda: service
    app.dependency_overrides[get_user_context] = lambda: MEMBER
    app.dependency_overrides[get_db_session] = lambda: object()
    app.dependency_overrides[get_audit_service] = lambda: AsyncMock()
    return TestClient(app, raise_server_exceptions=False)


def test_an_overlong_name_is_a_client_error_before_any_write() -> None:
    service = AsyncMock()

    response = _client(service).post("/v1/workspaces/acme/api-keys/", json={"name": "x" * 300})

    assert response.status_code == 422, response.text
    service.create_token.assert_not_called()


def test_a_failed_create_does_not_echo_the_exception() -> None:
    service = AsyncMock()
    service.create_token.side_effect = RuntimeError(LEAKED)

    response = _client(service).post("/v1/workspaces/acme/api-keys/", json={"name": "ci"})

    assert response.status_code == 500
    assert "token_hash" not in response.text
    assert "INSERT" not in response.text
    assert response.json() == {"detail": "Failed to create API key"}
