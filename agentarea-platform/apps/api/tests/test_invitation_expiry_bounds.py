"""An invitation's lifetime is bounded at the request, not discovered by the clock.

``expires_in_days`` feeds ``timedelta``; an absurd value overflowed it and the
request answered 500. Out-of-range lifetimes are a client mistake: 422.
"""

from unittest.mock import MagicMock

import pytest
from agentarea_api.api.v1 import workspace_invitations
from agentarea_api.main import app
from agentarea_common.auth.authorization import AuthorizationService
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.dependencies import get_user_context
from agentarea_common.auth.workspace_authorization import WorkspaceScopedAuthorizationService
from agentarea_common.di.container import register_singleton
from fastapi.testclient import TestClient

OWNER = UserContext(
    user_id="owner", workspace_id="ws-acme", workspace_slug="acme", admin_workspaces=["ws-acme"]
)


@pytest.fixture
def client():
    register_singleton(AuthorizationService, WorkspaceScopedAuthorizationService())
    service = MagicMock()
    app.dependency_overrides[get_user_context] = lambda: OWNER
    app.dependency_overrides[workspace_invitations.get_invitation_service] = lambda: service
    try:
        yield TestClient(app, raise_server_exceptions=False), service
    finally:
        app.dependency_overrides.pop(get_user_context, None)
        app.dependency_overrides.pop(workspace_invitations.get_invitation_service, None)


@pytest.mark.parametrize("days", [-10_000_000_000, -1, 0, 366, 10**12])
def test_an_out_of_range_lifetime_is_a_client_error(client, days):
    http, service = client

    response = http.post("/v1/workspaces/acme/invitations", json={"expires_in_days": days})

    assert response.status_code == 422, response.text
    service.create_invitation.assert_not_called()
