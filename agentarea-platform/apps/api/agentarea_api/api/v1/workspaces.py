"""Workspace listing API.

Returns the workspaces the current user can reach (their personal one
plus any joined via membership). The frontend uses this to resolve the
active workspace from the URL slug and to populate the switcher.
"""

import logging
from collections.abc import AsyncGenerator
from dataclasses import replace
from typing import Annotated

from agentarea_common.auth.authorization import is_workspace_admin
from agentarea_common.auth.context import UserContext, UserPrincipal
from agentarea_common.auth.dependencies import PrincipalDep, UnboundPrincipalDep
from agentarea_common.auth.route_authz import enforced_in_handler, unrestricted
from agentarea_common.base.repository_factory import RepositoryFactory
from agentarea_common.config import get_database
from agentarea_common.rebac import (
    KetoError,
    KetoUnavailableError,
    OpenFGAError,
    OpenFGAUnavailableError,
)
from agentarea_common.workspaces import (
    Workspace,
    WorkspaceRepository,
    WorkspaceService,
    get_workspace_membership_graph,
    list_workspace_ids_for_member,
)
from agentarea_common.workspaces.authority import administered_workspace_ids
from agentarea_governance.application import (
    GovernancePolicyService,
    provision_default_policies,
)
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ._access_control_grants import seed_workspace

logger = logging.getLogger(__name__)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with get_database().async_session_factory() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


def get_workspace_service(session: SessionDep, user: PrincipalDep) -> WorkspaceService:
    async def on_workspace_created(workspace: Workspace) -> None:
        """Provision a freshly created workspace so it is usable out of the box.

        Seeds the baseline governance policy row and the authorization graph
        (creator as admin, default root project). Fires for both personal
        (``ensure_personal``) and shared workspaces. Scoped to the new workspace
        (not the caller's current one) so rows land in the right place.

        Governance provisioning is part of workspace admission and therefore
        fails closed. A workspace without a runtime baseline must not appear
        ready and later execute under weaker implicit settings. The rows are
        written through the session that holds the uncommitted workspace row;
        ``WorkspaceService`` commits both together, or rolls both back if this
        raises.
        """
        # The creator administers what they are creating. Stated here because
        # ownership is resolved from committed rows and this one is not yet.
        ctx = UserContext(
            user_id=user.user_id, workspace_id=workspace.id, admin_workspaces=[workspace.id]
        )
        governance = GovernancePolicyService(RepositoryFactory(session, ctx))
        await provision_default_policies(governance, workspace.id)

    async def seed_authorization_graph(workspace: Workspace) -> None:
        """Write the workspace's graph tuples before its row exists.

        Before the row, deliberately. The graph is a second system and cannot
        join Postgres' transaction, so one of the two has to go first, and the
        harmless order is this one: tuples about a workspace id that was never
        inserted grant nobody anything, while a committed row with no tuples has
        no `Workspace#admin` and no root project -- its own owner is refused on
        every object the PDP governs, and nothing retries, because the row looks
        finished. Raising here means the create simply fails.
        """
        await seed_workspace(
            workspace_id=workspace.id,
            creator_user_id=workspace.owner_user_id,
        )

    return WorkspaceService(
        WorkspaceRepository(session),
        on_created=on_workspace_created,
        before_insert=seed_authorization_graph,
    )


WorkspaceServiceDep = Annotated[WorkspaceService, Depends(get_workspace_service)]


class WorkspaceResponse(BaseModel):
    id: str
    slug: str
    name: str
    # A workspace auto-provisioned for one user reuses that user's id, so
    # ``id == owner_user_id`` is what makes it personal. Sent instead of a
    # ``type`` field so the client derives the fact rather than trusting a
    # second copy of it.
    owner_user_id: str
    can_administer: bool


class CreateWorkspaceBody(BaseModel):
    name: str = Field(min_length=1, max_length=255)


async def list_reachable_workspaces(
    user: UserPrincipal, service: WorkspaceService
) -> list[Workspace]:
    """Every workspace *user* can reach: personal (provisioned on first call) + joined.

    An API key reaches only the workspace it was issued for.
    """
    graph = get_workspace_membership_graph()
    member_workspace_ids = (
        await list_workspace_ids_for_member(graph, user.user_id) if graph is not None else []
    )
    workspaces = await service.list_for_user(
        user.user_id,
        email=user.email,
        member_workspace_ids=member_workspace_ids,
    )
    if user.bound_workspace_id is not None:
        return [w for w in workspaces if w.id == user.bound_workspace_id]
    return workspaces


async def describe_workspaces(
    user: UserPrincipal, workspaces: list[Workspace]
) -> list[WorkspaceResponse]:
    """*workspaces* as *user* sees them, with the authority the admin-gated routes check."""
    if user.admin_workspaces is None:
        user = replace(user, admin_workspaces=await administered_workspace_ids(user.user_id))
    # Being listed is what makes each workspace reachable, so entering it cannot fail.
    user = replace(
        user,
        accessible_workspaces=[*(user.accessible_workspaces or []), *(w.id for w in workspaces)],
    )
    return [
        WorkspaceResponse(
            id=w.id,
            slug=w.slug,
            name=w.name,
            owner_user_id=w.owner_user_id,
            can_administer=await is_workspace_admin(user.enter(w.id, w.slug)),
        )
        for w in workspaces
    ]


router = APIRouter(tags=["workspaces"])


@router.post(
    "/workspaces",
    response_model=WorkspaceResponse,
    status_code=201,
    dependencies=[
        unrestricted(
            "any signed-in user may create a workspace and becomes its owner; "
            "an API key confined to one workspace may not"
        )
    ],
)
async def create_workspace(
    body: CreateWorkspaceBody,
    user: UnboundPrincipalDep,
    service: WorkspaceServiceDep,
) -> WorkspaceResponse:
    """Create a new shared workspace owned by the current user.

    Provisions the workspace row (baseline governance policies are seeded by
    the creation hook in ``get_workspace_service``) and grants the creator
    membership in the relationship graph so the workspace immediately shows up
    in their accessible list and the switcher.
    """
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Workspace name must not be empty")

    workspace = await service.create_shared(owner_user_id=user.user_id, name=name)

    # The creation hook already seeded the graph and raised on failure; this
    # re-assert is idempotent and kept so a deliberate create keeps answering
    # 503 with this endpoint's wording rather than the hook's.
    try:
        await seed_workspace(workspace_id=workspace.id, creator_user_id=user.user_id)
    except HTTPException:
        raise
    except (KetoError, KetoUnavailableError, OpenFGAError, OpenFGAUnavailableError) as exc:
        logger.exception("Failed to seed authorization graph for workspace %s", workspace.id)
        raise HTTPException(
            status_code=503, detail="Workspace authorization graph unavailable"
        ) from exc

    # Access was resolved before this row existed; its creator owns it.
    creator = replace(user, admin_workspaces=[*(user.admin_workspaces or []), workspace.id])
    [response] = await describe_workspaces(creator, [workspace])
    return response


@router.get(
    "/workspaces",
    response_model=list[WorkspaceResponse],
    dependencies=[enforced_in_handler("returns only the workspaces this user owns or belongs to")],
)
async def list_workspaces(
    user: PrincipalDep,
    service: WorkspaceServiceDep,
) -> list[WorkspaceResponse]:
    """List every workspace the current user can reach (personal + joined).

    Provisions the caller's personal workspace on first call, so a brand
    new user always gets at least one entry. Baseline governance policies are
    seeded by the workspace-creation hook (see ``get_workspace_service``).
    """
    return await describe_workspaces(user, await list_reachable_workspaces(user, service))
