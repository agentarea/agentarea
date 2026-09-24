"""What an invitee sees before joining, and what a caller the invitation is not for sees.

The invitee is not a member yet, so the preview carries exactly the workspace's
name, who invited them and until when — never the workspace's other data. An
invitation sent to an email address is refused to any other account, on preview
and on accept alike, without echoing a single field of it.
"""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from agentarea_api.api.v1 import workspace_invitations
from agentarea_api.main import app
from agentarea_common.auth.authorization import AuthorizationService
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.dependencies import get_user_context
from agentarea_common.auth.identity_directory import IdentityRecord
from agentarea_common.auth.workspace_authorization import WorkspaceScopedAuthorizationService
from agentarea_common.di.container import register_singleton
from agentarea_common.workspaces import WorkspaceInvitationService
from httpx import ASGITransport, AsyncClient

INVITER = "bb206374-f612-420d-acd0-b62051061c63"
INVITEE = "5b1edbaf-8480-4885-a003-78adc92ab513"
WORKSPACE_ID = "0d5c2f7e-8d6b-4b53-9a4e-1f7f3c2d9a10"
EXPIRES_AT = datetime(2026, 10, 1, 12, 0)


class FakeInvitationRepository:
    def __init__(self) -> None:
        self.by_hash: dict = {}

    async def add(self, invitation):
        invitation.id = "7f0e0a52-2a55-4f8a-9d0c-3d9f1c6b2e11"
        self.by_hash[invitation.token_hash] = invitation
        return invitation

    async def get_by_token_hash(self, token_hash):
        return self.by_hash.get(token_hash)

    async def update(self, invitation):
        return invitation


class FakeWorkspaceRepository:
    def __init__(self, _session) -> None:
        pass

    async def get(self, workspace_id):
        if workspace_id != WORKSPACE_ID:
            return None
        return SimpleNamespace(
            id=WORKSPACE_ID,
            slug="agentarea",
            name="AgentArea",
            owner_user_id=INVITER,
        )


@pytest.fixture
def service() -> WorkspaceInvitationService:
    register_singleton(AuthorizationService, WorkspaceScopedAuthorizationService())
    return WorkspaceInvitationService(FakeInvitationRepository())  # type: ignore[arg-type]


@pytest.fixture
def memberships():
    memberships = MagicMock()
    memberships.record = AsyncMock()
    return memberships


@pytest.fixture(autouse=True)
def directory(monkeypatch):
    directory = MagicMock()
    directory.resolve = AsyncMock(
        return_value={
            INVITER: IdentityRecord(INVITER, "artem@agentarea.ai", "Artem Astapenko"),
        }
    )
    monkeypatch.setattr(workspace_invitations, "get_identity_directory", lambda: directory)
    monkeypatch.setattr(workspace_invitations, "WorkspaceRepository", FakeWorkspaceRepository)
    return directory


def _client_as(email: str | None):
    user_context = MagicMock()
    user_context.user_id = INVITEE
    user_context.workspace_id = INVITEE
    user_context.email = email
    return user_context


@pytest_asyncio.fixture
async def make_client(service, memberships):
    async def _session():
        yield MagicMock()

    app.dependency_overrides[workspace_invitations.get_session] = _session
    app.dependency_overrides[workspace_invitations.get_invitation_service] = lambda: service
    app.dependency_overrides[workspace_invitations.get_membership_service] = lambda: memberships
    clients: list[AsyncClient] = []

    def _make(email: str | None) -> AsyncClient:
        app.dependency_overrides[get_user_context] = lambda: _client_as(email)
        client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        clients.append(client)
        return client

    try:
        yield _make
    finally:
        for client in clients:
            await client.aclose()
        for dependency in (
            workspace_invitations.get_session,
            workspace_invitations.get_invitation_service,
            workspace_invitations.get_membership_service,
            get_user_context,
        ):
            app.dependency_overrides.pop(dependency, None)


async def _invite(service, email: str | None = None) -> str:
    inviter = UserContext(
        user_id=INVITER, workspace_id=WORKSPACE_ID, admin_workspaces=[WORKSPACE_ID]
    )
    invitation, token = await service.create_invitation(
        actor=inviter, workspace_id=WORKSPACE_ID, email=email
    )
    invitation.expires_at = EXPIRES_AT
    return token


@pytest.mark.asyncio
async def test_preview_names_the_inviter_and_the_workspace_and_nothing_else(
    service, make_client
) -> None:
    token = await _invite(service, email="misha@agentarea.ai")

    response = await make_client("misha@agentarea.ai").post(
        "/v1/invitations/preview", json={"token": token}
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "workspace_name": "AgentArea",
        "inviter_display_name": "Artem Astapenko",
        "inviter_email": "artem@agentarea.ai",
        "expires_at": "2026-10-01T12:00:00Z",
    }


@pytest.mark.asyncio
async def test_preview_of_an_open_link_works_for_any_account(service, make_client) -> None:
    token = await _invite(service)

    response = await make_client("anyone@agentarea.ai").post(
        "/v1/invitations/preview", json={"token": token}
    )

    assert response.status_code == 200, response.text
    assert response.json()["workspace_name"] == "AgentArea"


@pytest.mark.asyncio
async def test_preview_leaves_an_unresolved_inviter_unresolved(
    service, make_client, directory
) -> None:
    directory.resolve.return_value = {}
    token = await _invite(service)

    response = await make_client("misha@agentarea.ai").post(
        "/v1/invitations/preview", json={"token": token}
    )

    assert response.status_code == 200, response.text
    assert response.json()["inviter_display_name"] is None
    assert response.json()["inviter_email"] is None


@pytest.mark.asyncio
async def test_preview_is_refused_to_an_account_it_is_not_addressed_to(
    service, make_client, directory
) -> None:
    token = await _invite(service, email="misha@agentarea.ai")

    response = await make_client("mark@agentarea.ai").post(
        "/v1/invitations/preview", json={"token": token}
    )

    assert response.status_code == 403, response.text
    assert response.json()["detail"] == "invitation addressed to another account"
    assert "AgentArea" not in response.text
    assert "Artem" not in response.text
    directory.resolve.assert_not_called()


@pytest.mark.asyncio
async def test_preview_of_an_unknown_token_is_not_found(make_client) -> None:
    response = await make_client("misha@agentarea.ai").post(
        "/v1/invitations/preview", json={"token": "not-a-real-token"}
    )

    assert response.status_code == 404, response.text


@pytest.mark.asyncio
async def test_accept_is_refused_to_an_account_it_is_not_addressed_to(
    service, make_client, memberships
) -> None:
    token = await _invite(service, email="misha@agentarea.ai")

    response = await make_client("mark@agentarea.ai").post(
        "/v1/invitations/accept", json={"token": token}
    )

    assert response.status_code == 403, response.text
    memberships.record.assert_not_called()


@pytest.mark.asyncio
async def test_accept_by_the_addressee_grants_membership(
    service, make_client, memberships
) -> None:
    token = await _invite(service, email="misha@agentarea.ai")

    response = await make_client("misha@agentarea.ai").post(
        "/v1/invitations/accept", json={"token": token}
    )

    assert response.status_code == 200, response.text
    assert response.json()["workspace_id"] == WORKSPACE_ID
    memberships.record.assert_awaited_once()
