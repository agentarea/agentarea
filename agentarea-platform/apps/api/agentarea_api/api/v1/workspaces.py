"""Workspace listing API.

Returns the workspaces the current user can reach (their personal one
plus any joined via membership). The frontend uses this to resolve the
active workspace from the URL slug and to populate the switcher.
"""

import logging
from collections.abc import AsyncGenerator
from typing import Annotated

from agentarea_common.auth.context import UserContext
from agentarea_common.auth.dependencies import UserContextDep
from agentarea_common.base.repository_factory import RepositoryFactory
from agentarea_common.config import get_database
from agentarea_common.workspaces import (
    Workspace,
    WorkspaceRepository,
    WorkspaceService,
    get_workspace_membership_graph,
    list_workspace_ids_for_member,
)
from agentarea_governance.application import (
    GovernancePolicyService,
    provision_default_policies,
)
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with get_database().async_session_factory() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


def get_workspace_service(session: SessionDep, user: UserContextDep) -> WorkspaceService:
    async def seed_default_policies(workspace: Workspace) -> None:
        """Seed baseline governance policies when a workspace is first created.

        Scoped to the new workspace (not the caller's current one) so the rows
        land in the right place. Never propagates failures — a workspace must
        still be created even if policy seeding hiccups — but logs loudly.
        """
        try:
            ctx = UserContext(user_id=user.user_id, workspace_id=workspace.id)
            governance = GovernancePolicyService(RepositoryFactory(session, ctx))
            created = await provision_default_policies(governance, workspace.id)
            if created:
                await session.commit()
        except Exception:
            logger.exception("failed to seed default policies for workspace %s", workspace.id)
            await session.rollback()

    return WorkspaceService(
        WorkspaceRepository(session),
        on_created=seed_default_policies,
    )


WorkspaceServiceDep = Annotated[WorkspaceService, Depends(get_workspace_service)]


class WorkspaceResponse(BaseModel):
    id: str
    slug: str
    name: str
    type: str


router = APIRouter(tags=["workspaces"])


@router.get("/workspaces", response_model=list[WorkspaceResponse])
async def list_workspaces(
    user: UserContextDep,
    service: WorkspaceServiceDep,
) -> list[WorkspaceResponse]:
    """List every workspace the current user can reach (personal + joined).

    Provisions the caller's personal workspace on first call, so a brand
    new user always gets at least one entry. Baseline governance policies are
    seeded by the workspace-creation hook (see ``get_workspace_service``).
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
    return [WorkspaceResponse(id=w.id, slug=w.slug, name=w.name, type=w.type) for w in workspaces]
