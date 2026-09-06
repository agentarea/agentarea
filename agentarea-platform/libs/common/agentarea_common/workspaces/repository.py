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

from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import (
    INVITATION_STATUS_PENDING,
    Workspace,
    WorkspaceInvitation,
    WorkspaceMembership,
)


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

    async def delete(self, workspace_id: str, user_id: str) -> bool:
        membership = await self.get(workspace_id, user_id)
        if membership is None:
            return False
        await self.session.delete(membership)
        await self.session.commit()
        return True


class WorkspaceRepository:
    """Persistence for the reified ``Workspace`` entity.

    Like the invitation/membership repos this does not extend
    ``WorkspaceScopedRepository``: a workspace is *the* scope, so scoping
    a workspace lookup by workspace would be circular.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, workspace: Workspace) -> Workspace:
        self.session.add(workspace)
        await self.session.commit()
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
