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

from agentarea_agents.tools.platform_authz import (
    enforced_in_handler,
    requires_workspace_admin,
    unrestricted,
)
from agentarea_agents_sdk.tools.decorator_tool import Toolset, tool_method
from agentarea_agents_sdk.tools.tool_definition import toolset
from agentarea_common.auth.identity_directory import get_identity_directory, identity_for
from agentarea_common.workspaces import (
    InvitationNotFound,
    MembershipRemovalRejected,
    WorkspaceInvitationRepository,
    WorkspaceInvitationService,
    WorkspaceMembershipRepository,
    WorkspaceMembershipService,
    WorkspaceRepository,
)
from agentarea_common.workspaces.invitation_email import deliver_invitation_for_workspace
from agentarea_common.workspaces.memberships import get_workspace_membership_graph

from .base import platform_context, platform_read_context


def _build_service(session) -> WorkspaceInvitationService:
    return WorkspaceInvitationService(WorkspaceInvitationRepository(session))


def _build_membership_service(session) -> WorkspaceMembershipService:
    graph = get_workspace_membership_graph()
    if graph is None:
        raise RuntimeError("Workspace membership graph is disabled")
    return WorkspaceMembershipService(
        membership_repo=WorkspaceMembershipRepository(session),
        workspace_repo=WorkspaceRepository(session),
        graph=graph,
    )


def _member(member, identities, user_ctx, *, owner_user_id: str) -> dict:
    identity = identity_for(
        member.user_id,
        identities,
        current_user_id=user_ctx.user_id,
        current_user_email=user_ctx.email,
    )
    return {
        "user_id": member.user_id,
        "email": identity.email,
        "display_name": identity.display_name,
        "joined_at": member.joined_at,
        "is_owner": member.user_id == owner_user_id,
        "is_you": member.user_id == user_ctx.user_id,
    }


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
    @unrestricted("members of the caller's own workspace, which the MCP bearer fixes")
    async def list(self) -> str:
        """List members of the current workspace."""
        async with platform_read_context() as (session, user_ctx, _repo, _broker, _secret):
            service = _build_membership_service(session)
            members = await service.list_members(user_ctx.workspace_id)
            owner_user_id = await service.owner_user_id(user_ctx.workspace_id)

            directory = get_identity_directory()
            identities = await directory.resolve([m.user_id for m in members]) if directory else {}

            return json.dumps(
                [
                    _member(member, identities, user_ctx, owner_user_id=owner_user_id)
                    for member in members
                ],
                default=str,
            )

    @tool_method(effect="privileged")
    @requires_workspace_admin()
    async def invite(self, email: str | None = None, expires_in_days: int | None = None) -> str:
        """Create an invitation. The plaintext token is returned exactly once."""
        async with platform_context() as (session, user_ctx, _repo, _broker, _secret):
            service = _build_service(session)
            kwargs: dict = {
                "actor": user_ctx,
                "workspace_id": user_ctx.workspace_id,
                "email": email,
            }
            if expires_in_days is not None:
                kwargs["expires_in_days"] = expires_in_days
            invitation, token = await service.create_invitation(**kwargs)
            delivery = await deliver_invitation_for_workspace(
                workspace_repo=WorkspaceRepository(session),
                workspace_id=user_ctx.workspace_id,
                recipient=email,
                token=token,
            )
            return json.dumps(
                {**_invitation(invitation), "token": token, "email_delivery": delivery},
                default=str,
            )

    @tool_method(effect="read")
    @requires_workspace_admin()
    async def list_invitations(self) -> str:
        """List pending invitations. Tokens are not returned."""
        async with platform_read_context() as (session, user_ctx, _repo, _broker, _secret):
            service = _build_service(session)
            invitations = await service.list_pending(
                actor=user_ctx, workspace_id=user_ctx.workspace_id
            )
            return json.dumps([_invitation(i) for i in invitations], default=str)

    @tool_method(effect="privileged")
    @requires_workspace_admin()
    async def revoke_invitation(self, invitation_id: str) -> str:
        """Revoke a pending invitation."""
        async with platform_context() as (session, user_ctx, _repo, _broker, _secret):
            service = _build_service(session)
            try:
                await service.revoke(
                    actor=user_ctx,
                    workspace_id=user_ctx.workspace_id,
                    invitation_id=UUID(invitation_id),
                )
            except InvitationNotFound:
                return json.dumps({"error": "Invitation not found"})
            return json.dumps({"revoked": True})

    @tool_method(effect="privileged")
    @enforced_in_handler("owner-only, enforced by WorkspaceMembershipService.remove")
    async def remove(self, user_id: str) -> str:
        """Remove a member from the workspace.

        The owner and the last remaining member cannot be removed, and only the
        owner can remove anyone other than themselves.
        """
        async with platform_context() as (session, user_ctx, _repo, _broker, _secret):
            try:
                await _build_membership_service(session).remove(
                    workspace_id=user_ctx.workspace_id,
                    target_user_id=user_id,
                    actor_user_id=user_ctx.user_id,
                )
            except MembershipRemovalRejected as exc:
                return json.dumps({"error": str(exc)})
            return json.dumps({"removed": True, "user_id": user_id})
