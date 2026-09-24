"""Workspace invitation and membership services."""

import hashlib
import logging
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError

from ..auth.authorization import assert_workspace_admin_of
from ..auth.context import UserContext
from .memberships import (
    MembershipGraph,
    grant_workspace_membership,
    list_workspace_member_ids,
    revoke_workspace_membership,
)
from .models import (
    INVITATION_STATUS_ACCEPTED,
    INVITATION_STATUS_PENDING,
    INVITATION_STATUS_REVOKED,
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


class InvitationAddressedElsewhere(Exception):  # noqa: N818
    """The invitation names an email that is not the caller's."""


class MembershipRemovalRejected(Exception):  # noqa: N818
    """A membership removal was refused by a workspace rule."""


class OwnerRemovalRejected(MembershipRemovalRejected):
    """The workspace owner keeps their own access until ownership moves."""


class LastMemberRemovalRejected(MembershipRemovalRejected):
    """Removing the final member would orphan the workspace and its resources."""


class MembershipRemovalForbidden(MembershipRemovalRejected):
    """Only the owner removes other people; everyone else may only leave."""


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class WorkspaceInvitationService:
    def __init__(
        self,
        invitation_repo: WorkspaceInvitationRepository,
    ) -> None:
        self.invitation_repo = invitation_repo

    async def create_invitation(
        self,
        *,
        actor: UserContext,
        workspace_id: str,
        email: str | None = None,
        expires_in_days: int = DEFAULT_EXPIRY_DAYS,
    ) -> tuple[WorkspaceInvitation, str]:
        """Create an invitation from ``actor``. Returns (invitation, plaintext_token).

        Only an admin of ``workspace_id`` may issue one: a join link grants
        everything membership grants. The plaintext token is returned exactly
        once and never persisted. Caller is responsible for delivering it (link
        in UI, email, Slack, etc.).
        """
        await assert_workspace_admin_of(actor, workspace_id)
        token = secrets.token_urlsafe(TOKEN_BYTES)
        invitation = WorkspaceInvitation(
            workspace_id=workspace_id,
            email=email,
            token_hash=_hash_token(token),
            invited_by=actor.user_id,
            status=INVITATION_STATUS_PENDING,
            expires_at=_utcnow() + timedelta(days=expires_in_days),
        )
        await self.invitation_repo.add(invitation)
        return invitation, token

    async def list_pending(
        self, *, actor: UserContext, workspace_id: str
    ) -> list[WorkspaceInvitation]:
        await assert_workspace_admin_of(actor, workspace_id)
        return await self.invitation_repo.list_pending(workspace_id)

    async def revoke(
        self, *, actor: UserContext, workspace_id: str, invitation_id: UUID | str
    ) -> WorkspaceInvitation:
        await assert_workspace_admin_of(actor, workspace_id)
        invitation = await self.invitation_repo.get_by_id(invitation_id)
        if invitation is None or invitation.workspace_id != workspace_id:
            raise InvitationNotFound(f"Invitation {invitation_id} not found")
        if invitation.status != INVITATION_STATUS_PENDING:
            return invitation
        invitation.status = INVITATION_STATUS_REVOKED
        return await self.invitation_repo.update(invitation)

    async def preview(
        self, *, token: str, user_id: str, user_email: str | None
    ) -> WorkspaceInvitation:
        """Return the invitation ``user_id`` could accept right now, or raise why not."""
        return await self._redeemable(token=token, user_id=user_id, user_email=user_email)

    async def accept(
        self, *, token: str, user_id: str, user_email: str | None
    ) -> WorkspaceInvitation:
        """Accept an invitation as ``user_id``.

        Idempotent for the same acceptor. The caller owns granting workspace
        membership in the configured authorization graph.
        """
        invitation = await self._redeemable(token=token, user_id=user_id, user_email=user_email)
        if invitation.status == INVITATION_STATUS_ACCEPTED:
            return invitation

        invitation.status = INVITATION_STATUS_ACCEPTED
        invitation.accepted_at = _utcnow()
        invitation.accepted_by_user_id = user_id
        await self.invitation_repo.update(invitation)

        return invitation

    async def _redeemable(
        self, *, token: str, user_id: str, user_email: str | None
    ) -> WorkspaceInvitation:
        invitation = await self.invitation_repo.get_by_token_hash(_hash_token(token))
        if invitation is None:
            raise InvitationNotFound("invalid token")

        # Checked before any state so a caller the invitation is not for learns
        # nothing about it.
        if not _is_addressed_to(invitation, user_email):
            raise InvitationAddressedElsewhere("invitation addressed to another account")

        if invitation.status == INVITATION_STATUS_REVOKED:
            raise InvitationRevoked("invitation revoked")

        if invitation.status == INVITATION_STATUS_ACCEPTED:
            if invitation.accepted_by_user_id == user_id:
                return invitation
            raise InvitationAlreadyAccepted("invitation already accepted")

        if invitation.is_expired(_utcnow()):
            raise InvitationExpired("invitation expired")

        return invitation


def _is_addressed_to(invitation: WorkspaceInvitation, email: str | None) -> bool:
    """An open link is for whoever holds it; an emailed one only for that address."""
    if invitation.email is None:
        return True
    if email is None:
        return False
    return invitation.email.strip().casefold() == email.strip().casefold()


@dataclass(frozen=True)
class WorkspaceMemberView:
    """One member as the product surfaces them.

    ``joined_at`` is ``None`` for members granted before membership rows were
    written; that is reported as unknown rather than guessed.
    """

    user_id: str
    joined_at: datetime | None
    invitation_id: UUID | None


class WorkspaceMembershipService:
    """Membership as a product operation: who is in, since when, and who may leave.

    The relationship graph stays the source of truth for *who* is a member —
    it is what authorization reads. The membership table adds the facts the
    graph cannot hold, currently the join date and the invitation that led to
    it, so a stale row can never resurrect access on its own.
    """

    def __init__(
        self,
        *,
        membership_repo: WorkspaceMembershipRepository,
        workspace_repo: WorkspaceRepository,
        graph: MembershipGraph,
    ) -> None:
        self.membership_repo = membership_repo
        self.workspace_repo = workspace_repo
        self.graph = graph

    async def record(
        self,
        *,
        workspace_id: str,
        user_id: str,
        invitation_id: UUID | None,
    ) -> None:
        """Grant membership and persist when it happened. Idempotent."""
        await grant_workspace_membership(self.graph, workspace_id=workspace_id, user_id=user_id)
        if await self.membership_repo.get(workspace_id, user_id) is not None:
            return
        await self.membership_repo.add(
            WorkspaceMembership(
                workspace_id=workspace_id,
                user_id=user_id,
                invitation_id=invitation_id,
            )
        )

    async def list_members(self, workspace_id: str) -> list[WorkspaceMemberView]:
        member_ids = await list_workspace_member_ids(self.graph, workspace_id)
        rows = {
            row.user_id: row for row in await self.membership_repo.list_for_workspace(workspace_id)
        }
        members = [
            WorkspaceMemberView(
                user_id=member_id,
                joined_at=getattr(rows.get(member_id), "created_at", None),
                invitation_id=getattr(rows.get(member_id), "invitation_id", None),
            )
            for member_id in member_ids
        ]
        return sorted(members, key=_member_order)

    async def remove(
        self,
        *,
        workspace_id: str,
        target_user_id: str,
        actor_user_id: str,
    ) -> None:
        owner_user_id = await self.owner_user_id(workspace_id)

        if target_user_id == owner_user_id:
            raise OwnerRemovalRejected(
                "The workspace owner cannot be removed; transfer ownership first."
            )
        if actor_user_id not in (owner_user_id, target_user_id):
            raise MembershipRemovalForbidden("Only the workspace owner can remove other members.")

        member_ids = await list_workspace_member_ids(self.graph, workspace_id)
        if target_user_id in member_ids and len(member_ids) <= 1:
            raise LastMemberRemovalRejected(
                "The last member cannot leave; the workspace would be unreachable."
            )

        await revoke_workspace_membership(
            self.graph, workspace_id=workspace_id, user_id=target_user_id
        )
        await self.membership_repo.delete(workspace_id, target_user_id)

    async def owner_user_id(self, workspace_id: str) -> str:
        """Who owns the workspace.

        Without a workspace row the id itself carries the answer: a workspace
        auto-provisioned for one user reuses that user's id.
        """
        workspace = await self.workspace_repo.get(workspace_id)
        return workspace.owner_user_id if workspace is not None else workspace_id


def _member_order(member: WorkspaceMemberView) -> tuple[bool, datetime, str]:
    joined_at = member.joined_at
    if joined_at is None:
        return (True, datetime.min, member.user_id)
    if joined_at.tzinfo is not None:
        joined_at = joined_at.astimezone(UTC).replace(tzinfo=None)
    return (False, joined_at, member.user_id)


class WorkspaceService:
    """Lifecycle of the reified ``Workspace`` entity.

    Owns provisioning of personal workspaces and creation of shared ones.
    Workspace membership is granted/revoked by the domain membership graph,
    outside this workspace-row lifecycle service.
    """

    def __init__(
        self,
        workspace_repo: WorkspaceRepository,
        on_created: Callable[[Workspace], Awaitable[None]] | None = None,
        before_insert: Callable[[Workspace], Awaitable[None]] | None = None,
    ) -> None:
        self.workspace_repo = workspace_repo
        # Fired exactly once when a workspace row is genuinely inserted (not on
        # idempotent re-reads). The composition layer wires cross-domain
        # provisioning here (e.g. baseline governance policies) without this
        # base library depending on those domains. It runs after the insert is
        # flushed and before it is committed, and writes through the same
        # session, so the row and what it provisions commit together: if it
        # raises, the workspace was never created.
        self._on_created = on_created
        # Fired with the fully-built row *before* it is inserted, for admission
        # work that lives outside Postgres and therefore cannot join its
        # transaction -- the authorization graph. Raising here means no row is
        # written at all, which is the failure worth having: the alternative is
        # a committed workspace whose tuples are missing, so its own owner is
        # refused on everything and nothing ever retries. Anything this writes
        # for a row that then fails to insert is inert: tuples about a workspace
        # id that does not exist grant nobody anything.
        self._before_insert = before_insert

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
        """Create a shared workspace row."""
        return await self._insert_with_unique_slug(
            slugify(name, fallback="workspace"),
            lambda slug: Workspace(
                id=str(uuid4()),
                slug=slug,
                name=name,
                owner_user_id=owner_user_id,
            ),
        )

    async def list_for_user(
        self,
        user_id: str,
        *,
        email: str | None = None,
        member_workspace_ids: list[str] | None = None,
    ) -> list[Workspace]:
        """List every workspace the user can reach.

        Provisions the personal workspace first so a brand-new user always
        gets at least one entry.
        """
        await self.ensure_personal(user_id, email=email)
        return await self.workspace_repo.list_for_user(
            user_id,
            member_workspace_ids=member_workspace_ids or [],
        )

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

        The insert and ``on_created`` share one transaction, committed only
        once both succeeded; any other failure rolls both back and re-raises.
        """
        session = self.workspace_repo.session
        for _ in range(5):
            workspace = build(await self._next_free_slug(slug_base))
            if self._before_insert is not None:
                await self._before_insert(workspace)
            try:
                if self._before_insert is not None:
                    await self._before_insert(workspace)
                created = await self.workspace_repo.add(workspace)
            except IntegrityError:
                await session.rollback()
                if on_conflict_get is not None:
                    existing = await on_conflict_get()
                    if existing is not None:
                        return existing
                continue
            try:
                if self._on_created is not None:
                    await self._on_created(created)
                await session.commit()
                return created
            except Exception:
                logger.error(
                    "workspace %s not created: admission failed", workspace.id, exc_info=True
                )
                await session.rollback()
                raise
        raise RuntimeError(f"could not allocate a unique slug from base {slug_base!r}")
