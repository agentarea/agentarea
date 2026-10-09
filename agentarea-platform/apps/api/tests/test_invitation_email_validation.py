"""An invitation's email is checked at the request, not by the database.

The column is ``String(320)``; a 5000-character ``email`` reached it and the
request answered 500. Nor was the format checked, so any string was stored as
the address an invitation is bound to. Both are a client mistake: 422.
"""

from unittest.mock import MagicMock

import pytest
from agentarea_api.api.v1 import workspace_invitations
from agentarea_api.api.v1.workspace_invitations import CreateInvitationBody
from agentarea_api.main import app
from agentarea_common.auth.authorization import AuthorizationService
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.dependencies import get_user_context
from agentarea_common.auth.workspace_authorization import WorkspaceScopedAuthorizationService
from agentarea_common.di.container import register_singleton
from fastapi.testclient import TestClient
from pydantic import ValidationError

OWNER = UserContext(
    user_id="owner", workspace_id="ws-acme", workspace_slug="acme", admin_workspaces=["ws-acme"]
)

def _short(value: object) -> str:
    text = repr(value)
    return text if len(text) <= 24 else f"{len(str(value))}-chars"


REFUSED = [
    "x" * 5000,
    "x" * 314 + "@ex.com",  # 321 characters: one over the column
    "",
    "not-an-email",
    "two@@ex.com",
    "no-domain-dot@localhost",
    "spaced out@ex.com",
    "@ex.com",
]


@pytest.mark.parametrize("email", REFUSED, ids=_short)
def test_a_malformed_or_overlong_email_is_refused(email: str) -> None:
    with pytest.raises(ValidationError):
        CreateInvitationBody(email=email)


@pytest.mark.parametrize(
    "email",
    [None, "bob@example.com", "first.last+tag@sub.example.co", "x" * 313 + "@ex.com"],
    ids=_short,
)
def test_a_wellformed_email_or_none_is_accepted(email: str | None) -> None:
    assert CreateInvitationBody(email=email).email == email


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


@pytest.mark.parametrize("email", ["x" * 5000, "not-an-email"], ids=_short)
def test_the_route_answers_422_before_creating_anything(client, email):
    http, service = client

    response = http.post("/v1/workspaces/acme/invitations", json={"email": email})

    assert response.status_code == 422, response.text
    service.create_invitation.assert_not_called()
