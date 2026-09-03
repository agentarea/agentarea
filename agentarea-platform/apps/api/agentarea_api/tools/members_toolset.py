"""MembersToolset — workspace membership and invitations.

Every tool acts on the caller's own workspace: the MCP mount is
workspace-scoped, and taking a ``workspace_id`` argument would offer callers a
handle on workspaces the graph would then have to refuse. Accepting an
invitation is deliberately absent — the acceptor is not yet a member of the
target workspace, so it belongs on the REST surface the invitee opens, not on
a member's tool surface.
"""

import json
from uuid import UUID

from agentarea_agents_sdk.tools.decorator_tool import Toolset, tool_method
from agentarea_agents_sdk.tools.tool_definition import toolset
from agentarea_common.workspaces import (
    InvitationNotFound,
    WorkspaceInvitationRepository,
    WorkspaceInvitationService,
)

from ..api.v1.workspace_invitations import _list_member_ids, _revoke_member
from .base import platform_context, platform_read_context


def _build_service(session) -> WorkspaceInvitationService:
    return WorkspaceInvitationService(WorkspaceInvitationRepository(session))


def _invitation(invitation) -> dict:
    return {
        "id": str(invitation.id),
        "email": invitation.email,
        "invited_by": invitation.invited_by,
        "status": invitation.status,
        "expires_at": invitation.expires_at,
        "created_at": invitation.created_at,
    }


@toolset(
    namespace="agentarea/members",
    display_name="Workspace Members",
    description="List workspace members, invite people, and revoke access.",
    category="platform",
    plane="govern",
)
class MembersToolset(Toolset):
    """Manage who is in the workspace: members, invitations, revocation."""

    @tool_method(effect="read")
    async def list(self) -> str:
        """List members of the current workspace."""
        async with platform_read_context() as (_session, user_ctx, _repo, _broker, _secret):
            member_ids = await _list_member_ids(user_ctx.workspace_id)
            return json.dumps(
                [
                    {
                        "user_id": member_id,
                        "email": user_ctx.email if member_id == user_ctx.user_id else None,
                        "is_you": member_id == user_ctx.user_id,
                    }
                    for member_id in member_ids
                ],
                default=str,
            )

    @tool_method(effect="privileged")
    async def invite(self, email: str | None = None, expires_in_days: int | None = None) -> str:
        """Create an invitation. The plaintext token is returned exactly once."""
        async with platform_context() as (session, user_ctx, _repo, _broker, _secret):
            service = _build_service(session)
            kwargs: dict = {
                "workspace_id": user_ctx.workspace_id,
                "invited_by": user_ctx.user_id,
                "email": email,
            }
            if expires_in_days is not None:
                kwargs["expires_in_days"] = expires_in_days
            invitation, token = await service.create_invitation(**kwargs)
            return json.dumps({**_invitation(invitation), "token": token}, default=str)

    @tool_method(effect="read")
    async def list_invitations(self) -> str:
        """List pending invitations. Tokens are not returned."""
        async with platform_read_context() as (session, user_ctx, _repo, _broker, _secret):
            service = _build_service(session)
            invitations = await service.list_pending(user_ctx.workspace_id)
            return json.dumps([_invitation(i) for i in invitations], default=str)

    @tool_method(effect="privileged")
    async def revoke_invitation(self, invitation_id: str) -> str:
        """Revoke a pending invitation."""
        async with platform_context() as (session, user_ctx, _repo, _broker, _secret):
            service = _build_service(session)
            try:
                await service.revoke(
                    workspace_id=user_ctx.workspace_id, invitation_id=UUID(invitation_id)
                )
            except InvitationNotFound:
                return json.dumps({"error": "Invitation not found"})
            return json.dumps({"revoked": True})

    @tool_method(effect="privileged")
    async def remove(self, user_id: str) -> str:
        """Remove a member from the workspace."""
        async with platform_context() as (_session, user_ctx, _repo, _broker, _secret):
            await _revoke_member(user_ctx.workspace_id, user_id)
            return json.dumps({"removed": True, "user_id": user_id})
