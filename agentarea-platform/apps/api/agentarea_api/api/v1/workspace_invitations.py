"""Workspace invitation and membership API endpoints.

Routes expose product-level workspace membership operations. The configured
relationship graph owns access decisions; persistence tables are only used for
invitation state.
"""

import logging
from collections.abc import AsyncGenerator
from typing import Annotated, NoReturn
from uuid import NAMESPACE_URL, UUID, uuid5

from agentarea_common.auth.dependencies import UserContextDep
from agentarea_common.auth.identity_directory import (
    IdentityRecord,
    get_identity_directory,
    identity_for,
)
from agentarea_common.auth.route_authz import (
    enforced_in_handler,
    requires_workspace_admin,
    unrestricted,
)
from agentarea_common.config import get_database
from agentarea_common.rebac import (
    KetoError,
    KetoUnavailableError,
    OpenFGAError,
    OpenFGAUnavailableError,
)
from agentarea_common.utils.types import UtcDatetime
from agentarea_common.workspaces import (
    InvitationAlreadyAccepted,
    InvitationExpired,
    InvitationNotFound,
    InvitationRevoked,
    LastMemberRemovalRejected,
    MembershipRemovalForbidden,
    OwnerRemovalRejected,
    WorkspaceInvitation,
    WorkspaceInvitationRepository,
    WorkspaceInvitationService,
    WorkspaceMembershipRepository,
    WorkspaceMembershipService,
    WorkspaceMemberView,
    WorkspaceRepository,
)
from agentarea_common.workspaces.invitation_email import (
    InvitationEmailDelivery,
    deliver_invitation_for_workspace,
)
from agentarea_common.workspaces.memberships import (
    get_workspace_membership_graph,
    list_workspace_member_ids,
)
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with get_database().async_session_factory() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


def get_invitation_service(session: SessionDep) -> WorkspaceInvitationService:
    return WorkspaceInvitationService(WorkspaceInvitationRepository(session))


InvitationServiceDep = Annotated[WorkspaceInvitationService, Depends(get_invitation_service)]


def get_membership_service(session: SessionDep) -> WorkspaceMembershipService:
    graph = get_workspace_membership_graph()
    if graph is None:
        raise HTTPException(status_code=503, detail="Workspace membership graph is disabled")
    return WorkspaceMembershipService(
        membership_repo=WorkspaceMembershipRepository(session),
        workspace_repo=WorkspaceRepository(session),
        graph=graph,
    )


MembershipServiceDep = Annotated[WorkspaceMembershipService, Depends(get_membership_service)]


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class CreateInvitationBody(BaseModel):
    email: str | None = None
    expires_in_days: int | None = None


class InvitationResponse(BaseModel):
    id: UUID
    workspace_id: str
    email: str | None
    invited_by: str
    invited_by_display_name: str | None
    status: str
    expires_at: UtcDatetime
    accepted_at: UtcDatetime | None
    accepted_by_user_id: str | None
    created_at: UtcDatetime

    model_config = {"from_attributes": True}


class InvitationCreatedResponse(InvitationResponse):
    """Same as InvitationResponse plus the plaintext token, returned ONCE."""

    token: str
    # Whether the link was emailed. Mail is best-effort, so the caller is told
    # the outcome instead of being left to assume the invitee was notified.
    email_delivery: InvitationEmailDelivery


class AcceptInvitationBody(BaseModel):
    token: str


class AcceptInvitationResponse(BaseModel):
    workspace_id: str
    user_id: str
    invitation_id: UUID


class MemberResponse(BaseModel):
    id: UUID
    workspace_id: str
    user_id: str
    # Nullable but not optional: an unresolved identity or an unknown join date
    # has to be stated by the caller, never acquired by forgetting the field.
    email: str | None
    display_name: str | None
    joined_at: UtcDatetime | None
    invitation_id: UUID | None
    is_owner: bool

    model_config = {"from_attributes": True}


def _invitation_to_response(
    invitation: WorkspaceInvitation,
    inviter: IdentityRecord | None,
) -> InvitationResponse:
    return InvitationResponse(
        id=invitation.id,
        workspace_id=invitation.workspace_id,
        email=invitation.email,
        invited_by=invitation.invited_by,
        invited_by_display_name=inviter.display_name if inviter else None,
        status=invitation.status,
        expires_at=invitation.expires_at,
        accepted_at=invitation.accepted_at,
        accepted_by_user_id=invitation.accepted_by_user_id,
        created_at=invitation.created_at,
    )


async def _members_to_response(
    workspace_id: str,
    members: list[WorkspaceMemberView],
    *,
    owner_user_id: str,
    current_user_id: str,
    current_user_email: str | None,
) -> list[MemberResponse]:
    """Attach identities to member ids.

    An id the directory cannot resolve stays unresolved — the caller renders an
    unknown user rather than being handed a guess.
    """
    identities = await _resolve_identities([member.user_id for member in members])
    responses: list[MemberResponse] = []
    for member in members:
        identity = identity_for(
            member.user_id,
            identities,
            current_user_id=current_user_id,
            current_user_email=current_user_email,
        )
        responses.append(
            MemberResponse(
                id=_stable_member_response_id(workspace_id, member.user_id),
                workspace_id=workspace_id,
                user_id=member.user_id,
                email=identity.email,
                display_name=identity.display_name,
                joined_at=member.joined_at,
                invitation_id=member.invitation_id,
                is_owner=member.user_id == owner_user_id,
            )
        )
    return responses


async def _resolve_identities(user_ids: list[str]) -> dict[str, IdentityRecord]:
    directory = get_identity_directory()
    if directory is None:
        return {}
    return await directory.resolve(user_ids)


def _stable_member_response_id(workspace_id: str, user_id: str) -> UUID:
    try:
        return UUID(str(user_id))
    except ValueError:
        return uuid5(NAMESPACE_URL, f"agentarea:workspace-member:{workspace_id}:{user_id}")


def _raise_membership_graph_unavailable(exc: Exception) -> NoReturn:
    raise HTTPException(status_code=503, detail="Workspace membership graph unavailable") from exc


GRAPH_ERRORS = (KetoError, KetoUnavailableError, OpenFGAError, OpenFGAUnavailableError)


async def _list_member_ids(workspace_id: str) -> list[str]:
    graph = get_workspace_membership_graph()
    if graph is None:
        raise HTTPException(status_code=503, detail="Workspace membership graph is disabled")
    try:
        return await list_workspace_member_ids(graph, workspace_id)
    except GRAPH_ERRORS as exc:
        logger.exception("Failed to list workspace memberships")
        _raise_membership_graph_unavailable(exc)


def _ensure_workspace_access(user: UserContextDep, workspace_id: str) -> None:
    """Owner-of-workspace bootstrap rule.

    Until permissions land in their own PR, the rule is: a user may
    operate on a workspace iff that workspace is in their
    accessible_workspaces list (resolved by AuthorizationService) OR
    the workspace_id equals their own user_id (personal workspace).
    """
    accessible = user.accessible_workspaces or [user.workspace_id]
    if workspace_id == user.user_id or workspace_id in accessible:
        return
    raise HTTPException(
        status_code=403,
        detail=f"Access denied to workspace {workspace_id}",
    )


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

router = APIRouter(tags=["workspace-invitations"])


# Invitations under /workspaces/{workspace_id}/invitations
@router.post(
    "/workspaces/{workspace_id}/invitations",
    response_model=InvitationCreatedResponse,
    status_code=201,
    dependencies=[requires_workspace_admin(workspace_param="workspace_id")],
)
async def create_invitation(
    workspace_id: str,
    body: CreateInvitationBody,
    user: UserContextDep,
    service: InvitationServiceDep,
    session: SessionDep,
):
    """Create an invitation link for the given workspace.

    The plaintext ``token`` is returned exactly once in the response.
    The caller delivers it however they want (link, email, Slack).
    """
    _ensure_workspace_access(user, workspace_id)
    kwargs: dict = {
        "workspace_id": workspace_id,
        "invited_by": user.user_id,
        "email": body.email,
    }
    if body.expires_in_days is not None:
        kwargs["expires_in_days"] = body.expires_in_days
    invitation, token = await service.create_invitation(**kwargs)
    delivery = await deliver_invitation_for_workspace(
        workspace_repo=WorkspaceRepository(session),
        workspace_id=invitation.workspace_id,
        recipient=body.email,
        token=token,
    )
    inviters = await _resolve_identities([invitation.invited_by])
    response = _invitation_to_response(invitation, inviters.get(invitation.invited_by))
    return InvitationCreatedResponse(**response.model_dump(), token=token, email_delivery=delivery)


@router.get(
    "/workspaces/{workspace_id}/invitations",
    response_model=list[InvitationResponse],
    dependencies=[requires_workspace_admin(workspace_param="workspace_id")],
)
async def list_invitations(
    workspace_id: str,
    user: UserContextDep,
    service: InvitationServiceDep,
):
    """List pending invitations for the workspace. Tokens are NOT returned."""
    _ensure_workspace_access(user, workspace_id)
    invitations = await service.list_pending(workspace_id)
    inviters = await _resolve_identities([i.invited_by for i in invitations])
    return [_invitation_to_response(i, inviters.get(i.invited_by)) for i in invitations]


@router.delete(
    "/workspaces/{workspace_id}/invitations/{invitation_id}",
    status_code=204,
    dependencies=[requires_workspace_admin(workspace_param="workspace_id")],
)
async def revoke_invitation(
    workspace_id: str,
    invitation_id: UUID,
    user: UserContextDep,
    service: InvitationServiceDep,
):
    """Revoke a pending invitation. Idempotent — already-resolved invitations are no-ops."""
    _ensure_workspace_access(user, workspace_id)
    try:
        await service.revoke(workspace_id=workspace_id, invitation_id=invitation_id)
    except InvitationNotFound as exc:
        raise HTTPException(status_code=404, detail="Invitation not found") from exc


# Accept lives at top-level /invitations/accept — by design the acceptor
# need not (yet) be a member of the target workspace.
@router.post(
    "/invitations/accept",
    response_model=AcceptInvitationResponse,
    dependencies=[
        unrestricted("bearer of the invitation token; there is no prior membership to check")
    ],
)
async def accept_invitation(
    body: AcceptInvitationBody,
    user: UserContextDep,
    service: InvitationServiceDep,
    memberships: MembershipServiceDep,
):
    """Accept an invitation as the authenticated user.

    Idempotent for the same acceptor.
    """
    try:
        invitation = await service.accept(token=body.token, user_id=user.user_id)
    except InvitationNotFound as exc:
        raise HTTPException(status_code=404, detail="invalid token") from exc
    except InvitationExpired as exc:
        raise HTTPException(status_code=410, detail="invitation expired") from exc
    except InvitationRevoked as exc:
        raise HTTPException(status_code=410, detail="invitation revoked") from exc
    except InvitationAlreadyAccepted as exc:
        raise HTTPException(status_code=409, detail="invitation already accepted") from exc

    try:
        await memberships.record(
            workspace_id=invitation.workspace_id,
            user_id=user.user_id,
            invitation_id=invitation.id,
        )
    except GRAPH_ERRORS as exc:
        logger.exception("Failed to grant workspace membership")
        _raise_membership_graph_unavailable(exc)

    return AcceptInvitationResponse(
        workspace_id=invitation.workspace_id,
        user_id=user.user_id,
        invitation_id=invitation.id,
    )


# Members under /workspaces/{workspace_id}/members
@router.get(
    "/workspaces/{workspace_id}/members",
    response_model=list[MemberResponse],
    dependencies=[
        enforced_in_handler("membership in the target workspace is asserted in the handler")
    ],
)
async def list_members(
    workspace_id: str,
    user: UserContextDep,
    memberships: MembershipServiceDep,
):
    _ensure_workspace_access(user, workspace_id)
    try:
        if workspace_id == user.user_id:
            await memberships.record(
                workspace_id=workspace_id, user_id=user.user_id, invitation_id=None
            )
        members = await memberships.list_members(workspace_id)
        owner_user_id = await memberships.owner_user_id(workspace_id)
    except GRAPH_ERRORS as exc:
        logger.exception("Failed to list workspace memberships")
        _raise_membership_graph_unavailable(exc)

    return await _members_to_response(
        workspace_id,
        members,
        owner_user_id=owner_user_id,
        current_user_id=user.user_id,
        current_user_email=user.email,
    )


@router.delete(
    "/workspaces/{workspace_id}/members/{user_id}",
    status_code=204,
    dependencies=[enforced_in_handler("owner-only, enforced by MembershipService.remove")],
)
async def remove_member(
    workspace_id: str,
    user_id: str,
    user: UserContextDep,
    memberships: MembershipServiceDep,
):
    """Remove a member from the workspace.

    The owner keeps their access until ownership moves, and the last member
    cannot leave — either would strand the workspace and everything in it.
    """
    _ensure_workspace_access(user, workspace_id)
    try:
        await memberships.remove(
            workspace_id=workspace_id,
            target_user_id=user_id,
            actor_user_id=user.user_id,
        )
    except MembershipRemovalForbidden as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (OwnerRemovalRejected, LastMemberRemovalRejected) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except GRAPH_ERRORS as exc:
        logger.exception("Failed to revoke workspace membership")
        _raise_membership_graph_unavailable(exc)
