"""Who an invitation is for, and what a caller it is not for can learn from it.

An open link (no email) is for whoever holds it. An emailed invitation is only
for the account signed in under that address: anyone else is refused before the
invitation's state is consulted, so a stray token does not even reveal whether
the invitation is still pending.
"""

from datetime import UTC, datetime, timedelta

import pytest
from agentarea_common.auth.authorization import AuthorizationService
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.workspace_authorization import WorkspaceScopedAuthorizationService
from agentarea_common.di.container import register_singleton
from agentarea_common.workspaces import (
    INVITATION_STATUS_ACCEPTED,
    INVITATION_STATUS_PENDING,
    INVITATION_STATUS_REVOKED,
    InvitationAddressedElsewhere,
    InvitationAlreadyAccepted,
    InvitationExpired,
    InvitationNotFound,
    WorkspaceInvitationService,
)

INVITEE = "invitee-user"
OTHER = "other-user"


class FakeInvitationRepository:
    def __init__(self) -> None:
        self.by_hash: dict = {}
        self.updates = 0

    async def add(self, invitation):
        self.by_hash[invitation.token_hash] = invitation
        return invitation

    async def get_by_token_hash(self, token_hash):
        return self.by_hash.get(token_hash)

    async def update(self, invitation):
        self.updates += 1
        return invitation


@pytest.fixture
def repo() -> FakeInvitationRepository:
    return FakeInvitationRepository()


@pytest.fixture
def service(repo) -> WorkspaceInvitationService:
    register_singleton(AuthorizationService, WorkspaceScopedAuthorizationService())
    return WorkspaceInvitationService(repo)  # type: ignore[arg-type]


async def _invite(service, email: str | None = None):
    owner = UserContext(
        user_id="owner-user", workspace_id="workspace-1", admin_workspaces=["workspace-1"]
    )
    return await service.create_invitation(actor=owner, workspace_id="workspace-1", email=email)


async def test_open_link_is_previewable_by_whoever_holds_it(service) -> None:
    invitation, token = await _invite(service)

    previewed = await service.preview(token=token, user_id=OTHER, user_email=None)

    assert previewed is invitation


async def test_emailed_invitation_matches_the_address_case_insensitively(service) -> None:
    invitation, token = await _invite(service, email="Jane@AgentArea.ai")

    previewed = await service.preview(
        token=token, user_id=INVITEE, user_email=" jane@agentarea.ai"
    )

    assert previewed is invitation


async def test_emailed_invitation_refuses_another_account(service) -> None:
    _, token = await _invite(service, email="jane@agentarea.ai")

    with pytest.raises(InvitationAddressedElsewhere):
        await service.preview(token=token, user_id=OTHER, user_email="mark@agentarea.ai")


async def test_emailed_invitation_refuses_a_caller_without_an_email(service) -> None:
    _, token = await _invite(service, email="jane@agentarea.ai")

    with pytest.raises(InvitationAddressedElsewhere):
        await service.preview(token=token, user_id=OTHER, user_email=None)


async def test_wrong_account_learns_nothing_about_the_invitation_state(service) -> None:
    invitation, token = await _invite(service, email="jane@agentarea.ai")
    invitation.status = INVITATION_STATUS_REVOKED

    with pytest.raises(InvitationAddressedElsewhere):
        await service.preview(token=token, user_id=OTHER, user_email="mark@agentarea.ai")


async def test_accept_refuses_another_account_and_leaves_the_invitation_pending(
    service, repo
) -> None:
    invitation, token = await _invite(service, email="jane@agentarea.ai")

    with pytest.raises(InvitationAddressedElsewhere):
        await service.accept(token=token, user_id=OTHER, user_email="mark@agentarea.ai")

    assert invitation.status == INVITATION_STATUS_PENDING
    assert invitation.accepted_by_user_id is None
    assert repo.updates == 0


async def test_accept_by_the_addressee_marks_it_accepted(service) -> None:
    invitation, token = await _invite(service, email="jane@agentarea.ai")

    await service.accept(token=token, user_id=INVITEE, user_email="jane@agentarea.ai")

    assert invitation.status == INVITATION_STATUS_ACCEPTED
    assert invitation.accepted_by_user_id == INVITEE


async def test_preview_does_not_consume_the_invitation(service, repo) -> None:
    invitation, token = await _invite(service)

    await service.preview(token=token, user_id=INVITEE, user_email=None)

    assert invitation.status == INVITATION_STATUS_PENDING
    assert repo.updates == 0


async def test_preview_reports_an_invitation_someone_else_accepted(service) -> None:
    _, token = await _invite(service)
    await service.accept(token=token, user_id=INVITEE, user_email=None)

    assert (await service.preview(token=token, user_id=INVITEE, user_email=None)).status == (
        INVITATION_STATUS_ACCEPTED
    )
    with pytest.raises(InvitationAlreadyAccepted):
        await service.preview(token=token, user_id=OTHER, user_email=None)


async def test_preview_reports_expiry(service) -> None:
    invitation, token = await _invite(service)
    invitation.expires_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1)

    with pytest.raises(InvitationExpired):
        await service.preview(token=token, user_id=INVITEE, user_email=None)


async def test_preview_of_an_unknown_token_is_not_found(service) -> None:
    with pytest.raises(InvitationNotFound):
        await service.preview(token="not-a-token", user_id=INVITEE, user_email=None)
