"""Workspace invitation and membership services."""

import hashlib
import logging
import secrets
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError

from .models import (
    INVITATION_STATUS_ACCEPTED,
    INVITATION_STATUS_PENDING,
    INVITATION_STATUS_REVOKED,
    WORKSPACE_TYPE_PERSONAL,
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
from .slug import slugify

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

    async def ensure_personal(self, user_id: str, *, email: str | None = None) -> Workspace:
        """Idempotently provision the user's personal workspace (id == user_id).

        The slug is derived from the email local-part (``jane@x.com`` ->
        ``jane``) so personal URLs stay human; falls back to ``user`` when
        no email is available. Race-safe: a concurrent first request loses
        the primary-key insert and re-reads the winner's row.
        """
        existing = await self.workspace_repo.get(user_id)
        if existing is not None:
            return existing

        slug_base = slugify(email.split("@", 1)[0], fallback="user") if email else "user"
        return await self._insert_with_unique_slug(
            slug_base,
            lambda slug: Workspace(
                id=user_id,
                slug=slug,
                type=WORKSPACE_TYPE_PERSONAL,
                name="Personal",
                owner_user_id=user_id,
            ),
            on_conflict_get=lambda: self.workspace_repo.get(user_id),
        )

    async def get(self, workspace_id: str) -> Workspace | None:
        return await self.workspace_repo.get(workspace_id)

    async def get_by_slug(self, slug: str) -> Workspace | None:
        return await self.workspace_repo.get_by_slug(slug)

    async def create_shared(self, *, owner_user_id: str, name: str) -> Workspace:
        """Create a shared workspace and make the creator its first member."""
        workspace = await self._insert_with_unique_slug(
            slugify(name, fallback="workspace"),
            lambda slug: Workspace(
                id=str(uuid4()),
                slug=slug,
                type=WORKSPACE_TYPE_SHARED,
                name=name,
                owner_user_id=owner_user_id,
            ),
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

    async def list_for_user(self, user_id: str, *, email: str | None = None) -> list[Workspace]:
        """List every workspace the user can reach (personal + memberships).

        Provisions the personal workspace first so a brand-new user always
        gets at least one entry.
        """
        await self.ensure_personal(user_id, email=email)
        return await self.workspace_repo.list_for_user(user_id)

    async def _next_free_slug(self, base: str) -> str:
        candidate = base
        suffix = 1
        while await self.workspace_repo.get_by_slug(candidate) is not None:
            suffix += 1
            candidate = f"{base}-{suffix}"
        return candidate

    async def _insert_with_unique_slug(
        self,
        slug_base: str,
        build: Callable[[str], Workspace],
        *,
        on_conflict_get: Callable[[], Awaitable[Workspace | None]] | None = None,
    ) -> Workspace:
        """Insert a workspace, resolving slug collisions (incl. races).

        ``_next_free_slug`` handles the common case; a concurrent insert
        that steals the slug (or, for personal workspaces, the id) raises
        ``IntegrityError`` — we roll back and retry, returning the winner's
        row via ``on_conflict_get`` when the conflict was on identity.
        """
        for _ in range(5):
            workspace = build(await self._next_free_slug(slug_base))
            try:
                return await self.workspace_repo.add(workspace)
            except IntegrityError:
                await self.workspace_repo.session.rollback()
                if on_conflict_get is not None:
                    existing = await on_conflict_get()
                    if existing is not None:
                        return existing
        raise RuntimeError(f"could not allocate a unique slug from base {slug_base!r}")
