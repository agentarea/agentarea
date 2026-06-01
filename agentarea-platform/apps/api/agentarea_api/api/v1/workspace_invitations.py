"""Workspace invitation and membership API endpoints.

Scope: workspace-only invitations (link-bearing token grants membership).
Authz beyond "must be a workspace member" — owner-only checks, role
presets, per-resource grants — is intentionally out of scope here. That
lives in the future Keto-integration PR.
"""

import logging
from collections.abc import AsyncGenerator
from datetime import datetime
from typing import Annotated
from uuid import UUID

from agentarea_common.auth.dependencies import UserContextDep
from agentarea_common.config import get_database
from agentarea_common.workspaces import (
    InvitationAlreadyAccepted,
    InvitationExpired,
    InvitationNotFound,
    InvitationRevoked,
    WorkspaceInvitation,
    WorkspaceInvitationRepository,
    WorkspaceInvitationService,
    WorkspaceMembership,
    WorkspaceMembershipRepository,
    WorkspaceMembershipService,
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
    return WorkspaceInvitationService(
        WorkspaceInvitationRepository(session),
        WorkspaceMembershipRepository(session),
    )


def get_membership_service(session: SessionDep) -> WorkspaceMembershipService:
    return WorkspaceMembershipService(WorkspaceMembershipRepository(session))


InvitationServiceDep = Annotated[WorkspaceInvitationService, Depends(get_invitation_service)]
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
    status: str
    expires_at: datetime
    accepted_at: datetime | None
    accepted_by_user_id: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class InvitationCreatedResponse(InvitationResponse):
    """Same as InvitationResponse plus the plaintext token, returned ONCE."""

    token: str


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
    joined_at: datetime
    invitation_id: UUID | None

    model_config = {"from_attributes": True}


def _invitation_to_response(invitation: WorkspaceInvitation) -> InvitationResponse:
    return InvitationResponse(
        id=invitation.id,
        workspace_id=invitation.workspace_id,
        email=invitation.email,
        invited_by=invitation.invited_by,
        status=invitation.status,
        expires_at=invitation.expires_at,
        accepted_at=invitation.accepted_at,
        accepted_by_user_id=invitation.accepted_by_user_id,
        created_at=invitation.created_at,
    )


def _membership_to_response(membership: WorkspaceMembership) -> MemberResponse:
    return MemberResponse(
        id=membership.id,
        workspace_id=membership.workspace_id,
        user_id=membership.user_id,
        joined_at=membership.created_at,
        invitation_id=UUID(str(membership.invitation_id)) if membership.invitation_id else None,
    )


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
)
async def create_invitation(
    workspace_id: str,
    body: CreateInvitationBody,
    user: UserContextDep,
    service: InvitationServiceDep,
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
    response = _invitation_to_response(invitation)
    return InvitationCreatedResponse(**response.model_dump(), token=token)


@router.get(
    "/workspaces/{workspace_id}/invitations",
    response_model=list[InvitationResponse],
)
async def list_invitations(
    workspace_id: str,
    user: UserContextDep,
    service: InvitationServiceDep,
):
    """List pending invitations for the workspace. Tokens are NOT returned."""
    _ensure_workspace_access(user, workspace_id)
    invitations = await service.list_pending(workspace_id)
    return [_invitation_to_response(i) for i in invitations]


@router.delete(
    "/workspaces/{workspace_id}/invitations/{invitation_id}",
    status_code=204,
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
)
async def accept_invitation(
    body: AcceptInvitationBody,
    user: UserContextDep,
    service: InvitationServiceDep,
):
    """Accept an invitation as the authenticated user.

    Idempotent: accepting twice (or accepting when already a member)
    returns the same membership.
    """
    try:
        invitation, membership = await service.accept(token=body.token, user_id=user.user_id)
    except InvitationNotFound as exc:
        raise HTTPException(status_code=404, detail="invalid token") from exc
    except InvitationExpired as exc:
        raise HTTPException(status_code=410, detail="invitation expired") from exc
    except InvitationRevoked as exc:
        raise HTTPException(status_code=410, detail="invitation revoked") from exc
    except InvitationAlreadyAccepted as exc:
        raise HTTPException(status_code=409, detail="invitation already accepted") from exc

    return AcceptInvitationResponse(
        workspace_id=invitation.workspace_id,
        user_id=membership.user_id,
        invitation_id=invitation.id,
    )


# Members under /workspaces/{workspace_id}/members
@router.get(
    "/workspaces/{workspace_id}/members",
    response_model=list[MemberResponse],
)
async def list_members(
    workspace_id: str,
    user: UserContextDep,
    service: MembershipServiceDep,
):
    _ensure_workspace_access(user, workspace_id)
    members = await service.list_members(workspace_id)
    return [_membership_to_response(m) for m in members]


@router.delete(
    "/workspaces/{workspace_id}/members/{user_id}",
    status_code=204,
)
async def remove_member(
    workspace_id: str,
    user_id: str,
    user: UserContextDep,
    service: MembershipServiceDep,
):
    """Remove a member from the workspace. Self-removal allowed; removing
    others requires the caller to be a member of the workspace (owner-only
    check belongs to the permissions PR).
    """
    _ensure_workspace_access(user, workspace_id)
    removed = await service.remove(workspace_id=workspace_id, user_id=user_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Membership not found")
