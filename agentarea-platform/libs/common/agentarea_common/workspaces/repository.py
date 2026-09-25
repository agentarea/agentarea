"""Repositories for workspace invitations and workspace rows.

These don't extend ``WorkspaceScopedRepository`` because:
- ``WorkspaceInvitation`` is created by a workspace member but the
  acceptance flow is performed by a different user who isn't yet
  scoped to the target workspace — a generic workspace-scope filter
  doesn't fit.
- ``Workspace`` is the scope root, so scoping a workspace lookup by workspace
  would be circular.

Both repositories accept ``UserContext`` per project convention but
use it only for explicit policy checks inside the calling service.
"""

from collections.abc import Collection
from datetime import datetime
from uuid import UUID

from sqlalchemy import column, delete, or_, select, table, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.context import UserContext
from ..events.base_events import EventEnvelope
from ..events.outbox_repository import OutboxRepository
from .models import (
    INVITATION_STATUS_ACCEPTED,
    INVITATION_STATUS_PENDING,
    INVITATION_STATUS_REVOKED,
    Workspace,
    WorkspaceInvitation,
    WorkspaceMembership,
)

MEMBERSHIP_ENDED = "workspace.membership.ended"


class WorkspaceInvitationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, invitation: WorkspaceInvitation) -> WorkspaceInvitation:
        self.session.add(invitation)
        await self.session.commit()
        await self.session.refresh(invitation)
        return invitation

    async def get_by_id(self, invitation_id: UUID | str) -> WorkspaceInvitation | None:
        result = await self.session.execute(
            select(WorkspaceInvitation).where(WorkspaceInvitation.id == invitation_id)
        )
        return result.scalar_one_or_none()

    async def get_by_token_hash(self, token_hash: str) -> WorkspaceInvitation | None:
        result = await self.session.execute(
            select(WorkspaceInvitation).where(WorkspaceInvitation.token_hash == token_hash)
        )
        return result.scalar_one_or_none()

    async def list_pending(self, workspace_id: str) -> list[WorkspaceInvitation]:
        result = await self.session.execute(
            select(WorkspaceInvitation)
            .where(WorkspaceInvitation.workspace_id == workspace_id)
            .where(WorkspaceInvitation.status == INVITATION_STATUS_PENDING)
            .order_by(WorkspaceInvitation.created_at.desc())
        )
        return list(result.scalars().all())

    async def update(self, invitation: WorkspaceInvitation) -> WorkspaceInvitation:
        await self.session.commit()
        await self.session.refresh(invitation)
        return invitation


class WorkspaceMembershipRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, membership: WorkspaceMembership) -> WorkspaceMembership:
        self.session.add(membership)
        await self.session.commit()
        await self.session.refresh(membership)
        return membership

    async def add_for_invitation(
        self, *, invitation_id: UUID, workspace_id: str, user_id: str, now: datetime
    ) -> bool:
        """Write the row and stamp the invitation granted, in one transaction.

        The invitation is re-read under a row lock and must still be accepted by
        ``user_id``: a removal that revoked it first wins, and nothing is written.
        """
        invitation = (
            await self.session.execute(
                select(WorkspaceInvitation)
                .where(WorkspaceInvitation.id == invitation_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if (
            invitation is None
            or invitation.status != INVITATION_STATUS_ACCEPTED
            or invitation.accepted_by_user_id != user_id
        ):
            await self.session.rollback()
            return False
        if invitation.membership_granted_at is None:
            if await self.get(workspace_id, user_id) is None:
                self.session.add(
                    WorkspaceMembership(
                        workspace_id=workspace_id, user_id=user_id, invitation_id=invitation_id
                    )
                )
            invitation.membership_granted_at = now
        await self.session.commit()
        return True

    async def get(self, workspace_id: str, user_id: str) -> WorkspaceMembership | None:
        result = await self.session.execute(
            select(WorkspaceMembership)
            .where(WorkspaceMembership.workspace_id == workspace_id)
            .where(WorkspaceMembership.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def list_for_workspace(self, workspace_id: str) -> list[WorkspaceMembership]:
        result = await self.session.execute(
            select(WorkspaceMembership)
            .where(WorkspaceMembership.workspace_id == workspace_id)
            .order_by(WorkspaceMembership.created_at.asc())
        )
        return list(result.scalars().all())

    async def list_for_user(self, user_id: str) -> list[WorkspaceMembership]:
        result = await self.session.execute(
            select(WorkspaceMembership).where(WorkspaceMembership.user_id == user_id)
        )
        return list(result.scalars().all())

    async def end(
        self, workspace_id: str, user_id: str, *, ended_by: str, emails: Collection[str]
    ) -> None:
        """Drop the row and every credential that could bring the user back.

        The invitation they joined through is revoked so replaying it is refused,
        and so is every pending invitation addressed to them: to ``emails`` or
        to an address they already joined through. Open links name nobody and
        stay open. Their API keys for the workspace are deactivated.
        ``api_keys`` is owned by the MCP domain, which depends on this library,
        so it is named as a bare table rather than imported.

        The graph revocation is queued in the same transaction, so a removal
        that commits always reaches the graph, whatever happens to the caller's
        own attempt.
        """
        await self.session.execute(
            delete(WorkspaceMembership)
            .where(WorkspaceMembership.workspace_id == workspace_id)
            .where(WorkspaceMembership.user_id == user_id)
        )
        joined_through = (
            await self.session.execute(
                select(WorkspaceInvitation.email)
                .where(WorkspaceInvitation.workspace_id == workspace_id)
                .where(WorkspaceInvitation.accepted_by_user_id == user_id)
                .where(WorkspaceInvitation.email.is_not(None))
            )
        ).scalars()
        addresses = {_address(email) for email in (*emails, *joined_through) if email}
        pending = (
            await self.session.execute(
                select(WorkspaceInvitation)
                .where(WorkspaceInvitation.workspace_id == workspace_id)
                .where(WorkspaceInvitation.status == INVITATION_STATUS_PENDING)
                .where(WorkspaceInvitation.email.is_not(None))
            )
        ).scalars()
        for invitation in pending:
            if invitation.email is not None and _address(invitation.email) in addresses:
                invitation.status = INVITATION_STATUS_REVOKED
        await self.session.execute(
            update(WorkspaceInvitation)
            .where(WorkspaceInvitation.workspace_id == workspace_id)
            .where(WorkspaceInvitation.accepted_by_user_id == user_id)
            .values(status=INVITATION_STATUS_REVOKED)
        )
        api_keys = table(
            "api_keys", column("workspace_id"), column("created_by"), column("is_active")
        )
        await self.session.execute(
            update(api_keys)
            .where(api_keys.c.workspace_id == workspace_id)
            .where(api_keys.c.created_by == user_id)
            .values(is_active=False)
        )
        await OutboxRepository(
            self.session, UserContext(user_id=ended_by, workspace_id=workspace_id)
        ).add(
            EventEnvelope(
                event_type=MEMBERSHIP_ENDED,
                data={"workspace_id": workspace_id, "user_id": user_id},
            ),
            aggregate_id=user_id,
            aggregate_type="workspace_membership",
        )
        await self.session.commit()


def _address(email: str) -> str:
    return email.strip().casefold()


class WorkspaceRepository:
    """Persistence for the reified ``Workspace`` entity.

    Like the invitation/membership repos this does not extend
    ``WorkspaceScopedRepository``: a workspace is *the* scope, so scoping
    a workspace lookup by workspace would be circular.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, workspace: Workspace) -> Workspace:
        """Stage the row in the caller's transaction; ``WorkspaceService`` commits it."""
        self.session.add(workspace)
        await self.session.flush()
        await self.session.refresh(workspace)
        return workspace

    async def get(self, workspace_id: str) -> Workspace | None:
        result = await self.session.execute(select(Workspace).where(Workspace.id == workspace_id))
        return result.scalar_one_or_none()

    async def get_by_slug(self, slug: str) -> Workspace | None:
        result = await self.session.execute(select(Workspace).where(Workspace.slug == slug))
        return result.scalar_one_or_none()

    async def list_for_user(
        self,
        user_id: str,
        *,
        member_workspace_ids: list[str],
    ) -> list[Workspace]:
        """Workspaces the user can reach: owned + explicitly granted memberships."""
        result = await self.session.execute(
            select(Workspace)
            .where(
                or_(
                    Workspace.owner_user_id == user_id,
                    Workspace.id.in_(member_workspace_ids),
                )
            )
            .order_by(Workspace.created_at.asc())
        )
        return list(result.scalars().all())

    async def list_owned_by_user(self, user_id: str) -> list[Workspace]:
        """List workspaces whose authoritative owner is ``user_id``."""
        result = await self.session.execute(
            select(Workspace)
            .where(Workspace.owner_user_id == user_id)
            .order_by(Workspace.created_at.asc())
        )
        return list(result.scalars().all())
