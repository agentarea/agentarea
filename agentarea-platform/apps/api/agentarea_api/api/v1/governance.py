"""Governance effective-policy preview and task-snapshot endpoints.

Source-of-truth policy CRUD now lives in ``/v1/policies`` (unified rules). This
module keeps the read-only resolution surfaces that the runtime and UI rely on:
the dry-run effective-policy preview and the immutable task policy snapshot.
"""

from typing import Annotated
from uuid import UUID

from agentarea_common.auth import UserContextDep
from agentarea_common.base.repository_factory import RepositoryFactory
from agentarea_common.infrastructure.database import get_db_session
from agentarea_governance.application import (
    GovernancePolicyResolver,
    GovernancePolicyService,
)
from agentarea_governance.domain.policies import (
    EffectivePolicy,
    PolicyDocument,
    PolicyValidationError,
)
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/governance", tags=["governance"])

DatabaseSessionDep = Annotated[AsyncSession, Depends(get_db_session)]


class EffectivePolicyResponse(BaseModel):
    effective_policy: EffectivePolicy


class EffectivePolicyPreviewRequest(BaseModel):
    """Body for dry-run effective-policy resolution."""

    model_config = ConfigDict(extra="forbid")

    agent_id: UUID | None = None
    task_policy: PolicyDocument | None = None


@router.post("/effective-policy/preview", response_model=EffectivePolicyResponse)
async def preview_effective_policy(
    payload: EffectivePolicyPreviewRequest,
    user_context: UserContextDep,
    db_session: DatabaseSessionDep,
) -> EffectivePolicyResponse:
    """Compute effective policy from rules without persisting a snapshot.

    Useful for UIs that need to show the merged workspace/agent/task ceiling
    before the user commits a task creation.
    """
    resolver = GovernancePolicyResolver(RepositoryFactory(db_session, user_context))
    try:
        effective = await resolver.resolve(
            workspace_id=user_context.workspace_id,
            agent_id=payload.agent_id,
            task_policy=payload.task_policy,
        )
    except PolicyValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return EffectivePolicyResponse(effective_policy=effective)


@router.get("/task-policy-snapshots/{task_id}", response_model=EffectivePolicyResponse)
async def get_task_policy_snapshot(
    task_id: UUID,
    user_context: UserContextDep,
    db_session: DatabaseSessionDep,
) -> EffectivePolicyResponse:
    """Read an immutable effective policy snapshot for a task."""
    service = GovernancePolicyService(RepositoryFactory(db_session, user_context))
    snapshot = await service.get_task_policy_snapshot(task_id=task_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Task policy snapshot not found")
    return EffectivePolicyResponse(effective_policy=snapshot)
