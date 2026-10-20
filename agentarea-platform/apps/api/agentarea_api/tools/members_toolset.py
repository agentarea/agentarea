"""MembersToolset — workspace membership and invitations.

Every tool acts on the workspace the call is bound to (the pinned URL or the
membership-checked ``workspace`` argument), never on one named by a tool's own
parameters. Accepting an
invitation is deliberately absent — the acceptor is not yet a member of the
target workspace, so it belongs on the REST surface the invitee opens, not on
a member's tool surface. Inviting, revoking an invitation and removing a member
need a signed-in user, as on the REST surface: an API key is refused.
"""

import builtins
import json
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from agentarea_agents_sdk.tools.base_tool import ToolError
from agentarea_agents_sdk.tools.decorator_tool import Toolset, tool_method
from agentarea_agents_sdk.tools.tool_authz import (
    enforced_in_handler,
    requires_workspace_admin,
    unrestricted,
)
from agentarea_agents_sdk.tools.tool_definition import toolset
from agentarea_common.audit import AuditService
from agentarea_common.auth.identity_directory import get_identity_directory, identity_for
from agentarea_common.workspaces import (
    INVITATION_STATUS_REVOKED,
    InvitationNotFound,
    MembershipRemovalRejected,
    WorkspaceInvitationRepository,
    WorkspaceInvitationService,
    WorkspaceMembershipRepository,
    WorkspaceMembershipService,
    WorkspaceRepository,
)
from agentarea_common.workspaces.invitation_email import (
    InvitationEmailDelivery,
    deliver_invitation_for_workspace,
)
from agentarea_common.workspaces.memberships import get_workspace_membership_graph
from pydantic import BaseModel, Field

from .base import platform_context, platform_read_context


class MemberOutput(BaseModel):
    user_id: str = Field(description="The member's user id.")
    email: str | None = Field(description="The member's email; null when it could not be resolved.")
    display_name: str | None = Field(
        description="The member's display name; null when it could not be resolved."
    )
    joined_at: datetime | None = Field(
        description="When the member joined; null for members granted before joins were recorded."
    )
    is_owner: bool = Field(description="Whether the member owns the workspace.")
    is_you: bool = Field(description="Whether the member is the caller.")


class InvitationOutput(BaseModel):
    id: str = Field(description="Invitation id (UUID).")
    email: str | None = Field(
        description="Address the invitation is for; null for an open link anyone can accept."
    )
    invited_by: str = Field(description="User id of whoever created the invitation.")
    status: str = Field(description="Invitation status, e.g. `pending` or `revoked`.")
    expires_at: datetime = Field(description="When the invitation stops being accepted.")
    created_at: datetime = Field(description="When the invitation was created.")


class InvitationCreated(InvitationOutput):
    token: str = Field(
        description="Plaintext invitation token, returned only here; it cannot be read again."
    )
    email_delivery: InvitationEmailDelivery = Field(
        description=(
            "Whether the invitation email was sent: `sent`, `not_requested` (no email "
            "given), `not_configured` (no mail set up) or `failed`; otherwise share the token by hand."
        )
    )


class InvitationRevoked(BaseModel):
    revoked: bool = Field(description="True once the invitation can no longer be accepted.")


class MemberRemoved(BaseModel):
    user_id: str = Field(description="User id of the removed member.")
    removed: bool | None = Field(
        default=None, description="True when the member's access is already gone."
    )
    status: Literal["revocation_pending"] | None = Field(
        default=None,
        description=(
            "`revocation_pending` when the membership has ended but its access is "
            "still being revoked."
        ),
    )
    detail: str | None = Field(default=None, description="What a pending status means.")


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
        identities=get_identity_directory(),
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

    open_world = False

    @tool_method(display_name="List members", effect="read", output=builtins.list[MemberOutput])
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

    @tool_method(
        display_name="Invite member",
        effect="privileged",
        open_world=True,
        output=InvitationCreated,
    )
    @requires_workspace_admin()
    async def invite(
        self,
        email: Annotated[
            str | None,
            Field(
                description=(
                    "Address to invite and email the link to; omit for an open link "
                    "anyone can accept."
                )
            ),
        ] = None,
        expires_in_days: Annotated[
            int | None,
            Field(description="Days until the invitation expires; omit for 7."),
        ] = None,
    ) -> str:
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
            await AuditService(session, user_ctx).record(
                "member.invite",
                "invitation",
                invitation.id,
                event_metadata={"resource_name": invitation.email},
            )
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

    @tool_method(
        display_name="List invitations",
        effect="read",
        output=builtins.list[InvitationOutput],
    )
    @requires_workspace_admin()
    async def list_invitations(self) -> str:
        """List pending invitations. Tokens are not returned."""
        async with platform_read_context() as (session, user_ctx, _repo, _broker, _secret):
            service = _build_service(session)
            invitations = await service.list_pending(
                actor=user_ctx, workspace_id=user_ctx.workspace_id
            )
            return json.dumps([_invitation(i) for i in invitations], default=str)

    @tool_method(
        display_name="Revoke invitation",
        effect="privileged",
        idempotent=True,
        output=InvitationRevoked,
    )
    @requires_workspace_admin()
    async def revoke_invitation(
        self,
        invitation_id: Annotated[
            str,
            Field(description="Invitation id (UUID), from `members_list_invitations`."),
        ],
    ) -> str:
        """Revoke a pending invitation."""
        async with platform_context() as (session, user_ctx, _repo, _broker, _secret):
            service = _build_service(session)
            try:
                invitation = await service.revoke(
                    actor=user_ctx,
                    workspace_id=user_ctx.workspace_id,
                    invitation_id=UUID(invitation_id),
                )
            except InvitationNotFound:
                raise ToolError("Invitation not found") from None
            if invitation.status == INVITATION_STATUS_REVOKED:
                await AuditService(session, user_ctx).record(
                    "member.invitation_revoke",
                    "invitation",
                    invitation.id,
                    event_metadata={"resource_name": invitation.email},
                )
            return json.dumps({"revoked": True})

    @tool_method(
        display_name="Remove member",
        effect="privileged",
        idempotent=True,
        output=MemberRemoved,
    )
    @enforced_in_handler("owner-only, enforced by WorkspaceMembershipService.remove")
    async def remove(
        self,
        user_id: Annotated[str, Field(description="User id of the member, from `members_list`.")],
    ) -> str:
        """Remove a member from the workspace.

        The owner and the last remaining member cannot be removed, and only the
        owner can remove anyone other than themselves.
        """
        async with platform_context() as (session, user_ctx, _repo, _broker, _secret):
            try:
                revoked = await _build_membership_service(session).remove(
                    workspace_id=user_ctx.workspace_id,
                    target_user_id=user_id,
                    actor_user_id=user_ctx.user_id,
                )
            except MembershipRemovalRejected as exc:
                raise ToolError(str(exc)) from exc
            await AuditService(session, user_ctx).record(
                "member.remove",
                "member",
                user_id,
                event_metadata={
                    "self_removal": user_id == user_ctx.user_id,
                    "access_revoked": revoked,
                },
            )
            if not revoked:
                return json.dumps(
                    {
                        "status": "revocation_pending",
                        "user_id": user_id,
                        "detail": "The membership has ended; its access is still being revoked.",
                    }
                )
            return json.dumps({"removed": True, "user_id": user_id})
