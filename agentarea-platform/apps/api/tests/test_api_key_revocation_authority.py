"""An API key may be revoked by the person who made it, or by a workspace admin.

``revoke_token`` looks the record up through the workspace-scoped repository and
deactivates it, so before this check any member could revoke a colleague's key
and cut off whatever that key was driving. The key itself is not an escalation
-- it authenticates as its creator and carries no authority they lack -- so
creating one stays member-level; destroying someone else's does not.
"""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from agentarea_api.api.v1.api_keys import get_api_key_service, router
from agentarea_common.auth.authorization import AuthorizationService
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.dependencies import get_user_context
from agentarea_common.auth.workspace_authorization import WorkspaceScopedAuthorizationService
from agentarea_common.di.container import register_singleton
from fastapi import FastAPI
from fastapi.testclient import TestClient

OWNER_ID = "user-creator"
TOKEN_ID = uuid4()


@pytest.fixture(autouse=True)
def _authz():
    register_singleton(AuthorizationService, WorkspaceScopedAuthorizationService())


def _client(context: UserContext) -> tuple[TestClient, AsyncMock]:
    service = AsyncMock()
    service.get_token.return_value = type("Key", (), {"created_by": OWNER_ID})()
    service.revoke_token.return_value = True
    app = FastAPI()
    app.include_router(router, prefix="/v1")
    app.dependency_overrides[get_api_key_service] = lambda: service
    app.dependency_overrides[get_user_context] = lambda: context
    return TestClient(app), service


def test_a_member_cannot_revoke_someone_elses_key() -> None:
    client, service = _client(UserContext(user_id="user-other", workspace_id="ws-acme"))

    response = client.delete(f"/v1/api-keys/{TOKEN_ID}")

    assert response.status_code == 403, response.text
    service.revoke_token.assert_not_awaited()


def test_the_creator_revokes_their_own_key() -> None:
    client, service = _client(UserContext(user_id=OWNER_ID, workspace_id="ws-acme"))

    response = client.delete(f"/v1/api-keys/{TOKEN_ID}")

    assert response.status_code == 204, response.text
    service.revoke_token.assert_awaited_once()


def test_a_workspace_admin_revokes_any_key() -> None:
    client, service = _client(
        UserContext(user_id="user-owner", workspace_id="ws-acme", admin_workspaces=["ws-acme"])
    )

    response = client.delete(f"/v1/api-keys/{TOKEN_ID}")

    assert response.status_code == 204, response.text
    service.revoke_token.assert_awaited_once()
