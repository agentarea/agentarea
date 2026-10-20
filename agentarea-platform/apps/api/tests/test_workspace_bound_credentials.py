"""An API key acts only in the workspace it was issued for — principal routes included.

Principal routes name no workspace, so the path cannot confine a key the way
``/v1/workspaces/{workspace}/...`` does. A key lacks the workspaces scope, so it
cannot create new workspaces or join others on its owner's behalf.
"""

from unittest.mock import MagicMock

import pytest
from agentarea_api.api.v1 import workspace_invitations, workspaces
from agentarea_api.main import app
from agentarea_common.auth.context import UserPrincipal
from agentarea_common.auth.credential import Credential
from agentarea_common.auth.dependencies import authenticate_principal, get_principal
from fastapi.testclient import TestClient

API_KEY = UserPrincipal(
    user_id="alice",
    bound_workspace_id="ws-issued",
    accessible_workspaces=["ws-issued"],
    credential=Credential(kind="api_key", key_id="key-1"),
)


@pytest.fixture
def client():
    service = MagicMock()
    app.dependency_overrides[authenticate_principal] = lambda: API_KEY
    app.dependency_overrides[get_principal] = lambda: API_KEY
    app.dependency_overrides[workspaces.get_workspace_service] = lambda: service
    app.dependency_overrides[workspace_invitations.get_invitation_service] = lambda: service
    app.dependency_overrides[workspace_invitations.get_membership_service] = lambda: service
    try:
        yield TestClient(app, raise_server_exceptions=False), service
    finally:
        for dependency in (
            authenticate_principal,
            get_principal,
            workspaces.get_workspace_service,
            workspace_invitations.get_invitation_service,
            workspace_invitations.get_membership_service,
        ):
            app.dependency_overrides.pop(dependency, None)


def test_an_api_key_cannot_create_a_workspace(client):
    http, service = client

    response = http.post("/v1/workspaces", json={"name": "Elsewhere"})

    assert response.status_code == 403, response.text
    assert "This credential cannot create workspaces" in response.json()["detail"]
    service.create_shared.assert_not_called()


def test_an_api_key_cannot_accept_an_invitation(client):
    http, service = client

    response = http.post("/v1/invitations/accept", json={"token": "t"})

    assert response.status_code == 403, response.text
    service.accept.assert_not_called()
