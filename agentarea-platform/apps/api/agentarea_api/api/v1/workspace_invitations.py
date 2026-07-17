"""Workspace invitation and membership API endpoints.

Routes expose product-level workspace membership operations. The configured
relationship graph owns access decisions; persistence tables are only used for
invitation state.
"""

import logging
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Annotated, NoReturn
from uuid import NAMESPACE_URL, UUID, uuid5

from agentarea_common.auth.dependencies import UserContextDep
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
    WorkspaceInvitation,
    WorkspaceInvitationRepository,
    WorkspaceInvitationService,
)
from agentarea_common.workspaces.memberships import (
    get_workspace_membership_graph,
    grant_workspace_membership,
    list_workspace_member_ids,
    revoke_workspace_membership,
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
    expires_at: UtcDatetime
    accepted_at: UtcDatetime | None
    accepted_by_user_id: str | None
    created_at: UtcDatetime

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
    email: str | None = None
    display_name: str | None = None
    joined_at: UtcDatetime
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


def _member_ids_to_response(
    workspace_id: str,
    member_ids: list[str],
    *,
    current_user_id: str,
    current_user_email: str | None,
    current_user_name: str | None,
) -> list[MemberResponse]:
    responses: list[MemberResponse] = []
    for member_id in member_ids:
        is_current_user = member_id == current_user_id
        display_name = current_user_name if is_current_user else None
        email = current_user_email if is_current_user else None
        responses.append(
            MemberResponse(
                id=_stable_member_response_id(workspace_id, member_id),
                workspace_id=workspace_id,
                user_id=member_id,
                email=email,
                display_name=display_name or email,
                joined_at=datetime.now(UTC),
                invitation_id=None,
            )
        )
    return responses


def _stable_member_response_id(workspace_id: str, user_id: str) -> UUID:
    try:
        return UUID(str(user_id))
    except ValueError:
        return uuid5(NAMESPACE_URL, f"agentarea:workspace-member:{workspace_id}:{user_id}")


def _raise_membership_graph_unavailable(exc: Exception) -> NoReturn:
    raise HTTPException(status_code=503, detail="Workspace membership graph unavailable") from exc


async def _grant_member(workspace_id: str, user_id: str) -> None:
    graph = get_workspace_membership_graph()
    if graph is None:
        raise HTTPException(status_code=503, detail="Workspace membership graph is disabled")
    try:
        await grant_workspace_membership(graph, workspace_id=workspace_id, user_id=user_id)
    except (KetoError, KetoUnavailableError, OpenFGAError, OpenFGAUnavailableError) as exc:
        logger.exception("Failed to grant workspace membership")
        _raise_membership_graph_unavailable(exc)


async def _revoke_member(workspace_id: str, user_id: str) -> None:
    graph = get_workspace_membership_graph()
    if graph is None:
        raise HTTPException(status_code=503, detail="Workspace membership graph is disabled")
    try:
        await revoke_workspace_membership(graph, workspace_id=workspace_id, user_id=user_id)
    except (KetoError, KetoUnavailableError, OpenFGAError, OpenFGAUnavailableError) as exc:
        logger.exception("Failed to revoke workspace membership")
        _raise_membership_graph_unavailable(exc)


async def _list_member_ids(workspace_id: str) -> list[str]:
    graph = get_workspace_membership_graph()
    if graph is None:
        raise HTTPException(status_code=503, detail="Workspace membership graph is disabled")
    try:
        return await list_workspace_member_ids(graph, workspace_id)
    except (KetoError, KetoUnavailableError, OpenFGAError, OpenFGAUnavailableError) as exc:
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

    await _grant_member(invitation.workspace_id, user.user_id)

    return AcceptInvitationResponse(
        workspace_id=invitation.workspace_id,
        user_id=user.user_id,
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
):
    _ensure_workspace_access(user, workspace_id)
    if workspace_id == user.user_id:
        await _grant_member(workspace_id, user.user_id)

    member_ids = await _list_member_ids(workspace_id)
    return _member_ids_to_response(
        workspace_id,
        member_ids,
        current_user_id=user.user_id,
        current_user_email=user.email,
        current_user_name=None,
    )


@router.delete(
    "/workspaces/{workspace_id}/members/{user_id}",
    status_code=204,
)
async def remove_member(
    workspace_id: str,
    user_id: str,
    user: UserContextDep,
):
    """Remove a member from the workspace."""
    _ensure_workspace_access(user, workspace_id)
    await _revoke_member(workspace_id, user_id)
