"""An API key cannot mint keys, invite members or manage access (#716).

A key acts as its creator, and a key issued for a workspace its creator owns
kept the owner's admin rights. So a leaked key could mint a ten-year key and
an invitation, and both outlived the revocation of the key that made them.
Every route that hands out or takes away access now needs a signed-in user.

The caller is resolved through the real ``get_user_context``: the key here is
bound to a workspace its creator owns, so it does reach admin, and the refusal
is what stops it -- not a missing grant.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from agentarea_api.api.deps.services import get_audit_service
from agentarea_api.api.v1 import access_control, workspace_invitations
from agentarea_api.api.v1.api_keys import get_api_key_service
from agentarea_api.main import app
from agentarea_common.auth.authorization import AuthorizationService
from agentarea_common.auth.context import UserPrincipal
from agentarea_common.auth.dependencies import authenticate_principal
from agentarea_common.auth.workspace_authorization import WorkspaceScopedAuthorizationService
from agentarea_common.config.database import get_db_session
from agentarea_common.di.container import register_singleton
from fastapi.testclient import TestClient

ACME = SimpleNamespace(id="ws-acme", slug="acme", owner_user_id="alice")
KEY_ID = str(uuid4())
TOKEN_ID = uuid4()
INVITATION_ID = uuid4()


def _api_key() -> UserPrincipal:
    return UserPrincipal(user_id="alice", bound_workspace_id=ACME.id, api_key_id=KEY_ID)


def _signed_in() -> UserPrincipal:
    return UserPrincipal(user_id="alice")


@pytest.fixture(autouse=True)
def _alice_owns_acme():
    register_singleton(AuthorizationService, WorkspaceScopedAuthorizationService())

    async def owned_and_named(user_id, *, slug=None, workspace_id=None):
        named = ACME if ACME.id == workspace_id or slug == ACME.slug else None
        return [ACME], named

    with (
        patch(
            "agentarea_common.auth.dependencies._owned_and_named_workspaces",
            new=owned_and_named,
        ),
        patch(
            "agentarea_common.auth.dependencies._member_workspace_ids",
            new=AsyncMock(return_value=[]),
        ),
    ):
        yield


class _Stand:
    def __init__(self, principal: UserPrincipal, monkeypatch) -> None:
        self.keys = AsyncMock()
        self.keys.create_token.return_value = (
            SimpleNamespace(
                id=TOKEN_ID,
                name="ci",
                token_prefix="aat_abc",
                is_active=True,
                expires_at=None,
                access_count=0,
                last_accessed_at=None,
                created_at="2026-10-01T00:00:00Z",
                agent_id=None,
            ),
            "aat_raw",
        )
        self.keys.get_token.return_value = SimpleNamespace(
            created_by="alice", name="ci", token_prefix="aat_abc"
        )
        self.keys.revoke_token.return_value = True
        self.invitations = AsyncMock()
        self.invitations.create_invitation.return_value = (
            SimpleNamespace(
                id=INVITATION_ID,
                workspace_id=ACME.id,
                email=None,
                invited_by="alice",
                status="pending",
                expires_at="2026-10-08T00:00:00Z",
                accepted_at=None,
                accepted_by_user_id=None,
                created_at="2026-10-01T00:00:00Z",
            ),
            "invite-token",
        )
        self.invitations.revoke.return_value = SimpleNamespace(
            id=INVITATION_ID, email=None, status="revoked"
        )
        self.memberships = AsyncMock()
        self.audit = AsyncMock()
        self.graph = MagicMock()
        monkeypatch.setattr(
            workspace_invitations,
            "deliver_invitation_for_workspace",
            AsyncMock(return_value="not_requested"),
        )
        monkeypatch.setattr(
            workspace_invitations, "_resolve_identities", AsyncMock(return_value={})
        )
        monkeypatch.setattr(access_control, "get_graph_client", lambda: self.graph)
        overrides = {
            authenticate_principal: lambda: principal,
            get_api_key_service: lambda: self.keys,
            get_audit_service: lambda: self.audit,
            get_db_session: lambda: MagicMock(),
            workspace_invitations.get_session: lambda: MagicMock(),
            workspace_invitations.get_invitation_service: lambda: self.invitations,
            workspace_invitations.get_membership_service: lambda: self.memberships,
        }
        app.dependency_overrides.update(overrides)
        self._overrides = overrides
        self.http = TestClient(app, raise_server_exceptions=False)

    def close(self) -> None:
        for dependency in self._overrides:
            app.dependency_overrides.pop(dependency, None)


@pytest.fixture
def stand(monkeypatch):
    stands: list[_Stand] = []

    def make(principal: UserPrincipal) -> _Stand:
        built = _Stand(principal, monkeypatch)
        stands.append(built)
        return built

    yield make
    for built in stands:
        built.close()


GRANT = {
    "namespace": "Agent",
    "object": str(uuid4()),
    "relation": "manager",
    "subject_id": "mallory",
}

REFUSED = [
    ("post", "/v1/workspaces/acme/api-keys/", {"name": "backdoor", "expires_in_days": 3650}),
    ("delete", f"/v1/workspaces/acme/api-keys/{TOKEN_ID}", None),
    ("post", "/v1/workspaces/acme/invitations", {}),
    ("delete", f"/v1/workspaces/acme/invitations/{INVITATION_ID}", None),
    ("delete", "/v1/workspaces/acme/members/bob", None),
    ("post", "/v1/workspaces/acme/access-control/relationships", GRANT),
    ("delete", "/v1/workspaces/acme/access-control/relationships", GRANT),
]


@pytest.mark.parametrize(
    ("method", "path", "body"),
    REFUSED,
    ids=[
        "create-key",
        "revoke-key",
        "create-invitation",
        "revoke-invitation",
        "remove-member",
        "grant-access",
        "revoke-access",
    ],
)
def test_an_api_key_is_refused(stand, method, path, body) -> None:
    s = stand(_api_key())

    response = s.http.request(method.upper(), path, json=body)

    assert response.status_code == 403, response.text
    assert "An API key cannot" in response.json()["detail"]
    assert "sign in as a user" in response.json()["detail"]
    s.keys.create_token.assert_not_awaited()
    s.keys.revoke_token.assert_not_awaited()
    s.invitations.create_invitation.assert_not_awaited()
    s.invitations.revoke.assert_not_awaited()
    s.memberships.remove.assert_not_awaited()
    s.graph.write_tuple.assert_not_called()
    s.graph.delete_tuple.assert_not_called()
    s.audit.record.assert_not_awaited()


def test_the_key_still_reaches_what_it_was_issued_for(stand) -> None:
    """The refusal is narrow: the key keeps reading its workspace's keys."""
    s = stand(_api_key())
    s.keys.list_tokens.return_value = []

    response = s.http.get("/v1/workspaces/acme/api-keys/")

    assert response.status_code == 200, response.text


def test_a_signed_in_user_creates_a_key(stand) -> None:
    s = stand(_signed_in())

    response = s.http.post(
        "/v1/workspaces/acme/api-keys/", json={"name": "ci", "expires_in_days": 30}
    )

    assert response.status_code == 201, response.text
    assert response.json()["token"] == "aat_raw"
    s.keys.create_token.assert_awaited_once()


def test_a_signed_in_user_revokes_a_key(stand) -> None:
    s = stand(_signed_in())

    response = s.http.delete(f"/v1/workspaces/acme/api-keys/{TOKEN_ID}")

    assert response.status_code == 204, response.text
    s.keys.revoke_token.assert_awaited_once()


def test_a_signed_in_owner_invites_a_member(stand) -> None:
    s = stand(_signed_in())

    response = s.http.post("/v1/workspaces/acme/invitations", json={})

    assert response.status_code == 201, response.text
    assert response.json()["token"] == "invite-token"
    s.invitations.create_invitation.assert_awaited_once()


def test_a_signed_in_owner_revokes_an_invitation(stand) -> None:
    s = stand(_signed_in())

    response = s.http.delete(f"/v1/workspaces/acme/invitations/{INVITATION_ID}")

    assert response.status_code == 204, response.text
    s.invitations.revoke.assert_awaited_once()
