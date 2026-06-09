"""Workspace listing API.

Returns the workspaces the current user can reach (their personal one
plus any joined via membership). The frontend uses this to resolve the
active workspace from the URL slug and to populate the switcher.
"""

import logging
from collections.abc import AsyncGenerator
from typing import Annotated

from agentarea_common.auth.dependencies import UserContextDep
from agentarea_common.config import get_database
from agentarea_common.workspaces import (
    WorkspaceMembershipRepository,
    WorkspaceRepository,
    WorkspaceService,
)
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with get_database().async_session_factory() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


def get_workspace_service(session: SessionDep) -> WorkspaceService:
    return WorkspaceService(
        WorkspaceRepository(session),
        WorkspaceMembershipRepository(session),
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
    new user always gets at least one entry.
    """
    workspaces = await service.list_for_user(user.user_id, email=user.email)
    return [WorkspaceResponse(id=w.id, slug=w.slug, name=w.name, type=w.type) for w in workspaces]
