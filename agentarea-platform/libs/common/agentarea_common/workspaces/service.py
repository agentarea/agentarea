"""Workspace invitation and membership services."""

import hashlib
import logging
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from .models import (
    INVITATION_STATUS_ACCEPTED,
    INVITATION_STATUS_PENDING,
    INVITATION_STATUS_REVOKED,
    WORKSPACE_TYPE_SHARED,
    Workspace,
    WorkspaceInvitation,
    WorkspaceMembership,
)
from .repository import (
    WorkspaceInvitationRepository,
    WorkspaceMembershipRepository,
    WorkspaceRepository,
)

logger = logging.getLogger(__name__)

DEFAULT_EXPIRY_DAYS = 7
TOKEN_BYTES = 32


class InvitationNotFound(Exception):  # noqa: N818
    pass


class InvitationExpired(Exception):  # noqa: N818
    pass


class InvitationRevoked(Exception):  # noqa: N818
    pass


class InvitationAlreadyAccepted(Exception):  # noqa: N818
    pass


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class WorkspaceInvitationService:
    def __init__(
        self,
        invitation_repo: WorkspaceInvitationRepository,
        membership_repo: WorkspaceMembershipRepository,
    ) -> None:
        self.invitation_repo = invitation_repo
        self.membership_repo = membership_repo

    async def create_invitation(
        self,
        *,
        workspace_id: str,
        invited_by: str,
        email: str | None = None,
        expires_in_days: int = DEFAULT_EXPIRY_DAYS,
    ) -> tuple[WorkspaceInvitation, str]:
        """Create an invitation. Returns (invitation, plaintext_token).

        The plaintext token is returned exactly once and never persisted.
        Caller is responsible for delivering it (link in UI, email,
        Slack, etc.).
        """
        token = secrets.token_urlsafe(TOKEN_BYTES)
        invitation = WorkspaceInvitation(
            workspace_id=workspace_id,
            email=email,
            token_hash=_hash_token(token),
            invited_by=invited_by,
            status=INVITATION_STATUS_PENDING,
            expires_at=_utcnow() + timedelta(days=expires_in_days),
        )
        await self.invitation_repo.add(invitation)
        return invitation, token

    async def list_pending(self, workspace_id: str) -> list[WorkspaceInvitation]:
        return await self.invitation_repo.list_pending(workspace_id)

    async def revoke(self, *, workspace_id: str, invitation_id: UUID | str) -> WorkspaceInvitation:
        invitation = await self.invitation_repo.get_by_id(invitation_id)
        if invitation is None or invitation.workspace_id != workspace_id:
            raise InvitationNotFound(f"Invitation {invitation_id} not found")
        if invitation.status != INVITATION_STATUS_PENDING:
            return invitation
        invitation.status = INVITATION_STATUS_REVOKED
        return await self.invitation_repo.update(invitation)

    async def accept(
        self, *, token: str, user_id: str
    ) -> tuple[WorkspaceInvitation, WorkspaceMembership]:
        """Accept an invitation as ``user_id``.

        Idempotent on (workspace_id, user_id): if the user is already a
        member of the target workspace, the invitation is still marked
        accepted (if pending) and the existing membership is returned.
        """
        invitation = await self.invitation_repo.get_by_token_hash(_hash_token(token))
        if invitation is None:
            raise InvitationNotFound("invalid token")

        if invitation.status == INVITATION_STATUS_REVOKED:
            raise InvitationRevoked("invitation revoked")

        if invitation.status == INVITATION_STATUS_ACCEPTED:
            existing = await self.membership_repo.get(invitation.workspace_id, user_id)
            if existing is not None:
                return invitation, existing
            raise InvitationAlreadyAccepted("invitation already accepted")

        if invitation.is_expired(_utcnow()):
            raise InvitationExpired("invitation expired")

        existing = await self.membership_repo.get(invitation.workspace_id, user_id)
        if existing is not None:
            membership = existing
        else:
            membership = await self.membership_repo.add(
                WorkspaceMembership(
                    workspace_id=invitation.workspace_id,
                    user_id=user_id,
                    invitation_id=invitation.id,
                )
            )

        invitation.status = INVITATION_STATUS_ACCEPTED
        invitation.accepted_at = _utcnow()
        invitation.accepted_by_user_id = user_id
        await self.invitation_repo.update(invitation)

        return invitation, membership


class WorkspaceMembershipService:
    def __init__(self, membership_repo: WorkspaceMembershipRepository) -> None:
        self.membership_repo = membership_repo

    async def list_members(self, workspace_id: str) -> list[WorkspaceMembership]:
        return await self.membership_repo.list_for_workspace(workspace_id)

    async def is_member(self, workspace_id: str, user_id: str) -> bool:
        return (await self.membership_repo.get(workspace_id, user_id)) is not None

    async def remove(self, *, workspace_id: str, user_id: str) -> bool:
        return await self.membership_repo.delete(workspace_id, user_id)


class WorkspaceService:
    """Lifecycle of the reified ``Workspace`` entity.

    Owns provisioning of personal workspaces and creation of shared ones.
    Membership remains the source of truth for *who* can reach a shared
    workspace; this service just keeps the workspace row and the owner's
    membership in sync on create.
    """

    def __init__(
        self,
        workspace_repo: WorkspaceRepository,
        membership_repo: WorkspaceMembershipRepository,
    ) -> None:
        self.workspace_repo = workspace_repo
        self.membership_repo = membership_repo

    async def ensure_personal(self, user_id: str) -> Workspace:
        """Idempotently provision the user's personal workspace (id == user_id)."""
        return await self.workspace_repo.get_or_create_personal(user_id)

    async def get(self, workspace_id: str) -> Workspace | None:
        return await self.workspace_repo.get(workspace_id)

    async def create_shared(self, *, owner_user_id: str, name: str) -> Workspace:
        """Create a shared workspace and make the creator its first member."""
        workspace = await self.workspace_repo.add(
            Workspace(
                id=str(uuid4()),
                type=WORKSPACE_TYPE_SHARED,
                name=name,
                owner_user_id=owner_user_id,
            )
        )
        if await self.membership_repo.get(workspace.id, owner_user_id) is None:
            await self.membership_repo.add(
                WorkspaceMembership(
                    workspace_id=workspace.id,
                    user_id=owner_user_id,
                    invitation_id=None,
                )
            )
        return workspace

    async def list_for_user(self, user_id: str) -> list[Workspace]:
        """List every workspace the user can reach (personal + memberships).

        Provisions the personal workspace first so a brand-new user always
        gets at least one entry.
        """
        await self.ensure_personal(user_id)
        return await self.workspace_repo.list_for_user(user_id)
