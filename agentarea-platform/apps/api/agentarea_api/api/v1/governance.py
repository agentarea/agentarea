"""Governance effective-policy preview and task-snapshot endpoints.

Source-of-truth policy CRUD now lives in ``/v1/policies`` (unified rules). This
module keeps the read-only resolution surfaces that the runtime and UI rely on:
the dry-run effective-policy preview and the immutable task policy snapshot.
"""

from typing import Annotated
from uuid import UUID

from agentarea_agents.application.temporal_workflow_service import TemporalWorkflowService
from agentarea_api.api.deps.services import get_temporal_workflow_service
from agentarea_common.auth import UserContextDep
from agentarea_common.base.repository_factory import RepositoryFactory
from agentarea_common.config.database import get_db_session
from agentarea_governance.application import GovernancePolicyResolver
from agentarea_governance.domain.policies import (
    EffectivePolicy,
    PolicyDocument,
    PolicyValidationError,
    effective_policy_from_json,
)
from agentarea_tasks.infrastructure.repository import TaskRepository
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
    workflow_service: Annotated[TemporalWorkflowService, Depends(get_temporal_workflow_service)],
) -> EffectivePolicyResponse:
    """Read the effective governance policy for a task.

    The effective policy is no longer persisted; it is served on demand by
    querying the task's Temporal workflow, where it lives in workflow state.
    """
    task_repository = RepositoryFactory(db_session, user_context).create_repository(TaskRepository)
    task = await task_repository.get_task(task_id)
    if task is None or not task.execution_id:
        raise HTTPException(status_code=404, detail="Task policy snapshot not found")

    effective_policy = await workflow_service.get_effective_policy(task.execution_id)
    if effective_policy is None:
        raise HTTPException(status_code=404, detail="Task policy snapshot not found")

    return EffectivePolicyResponse(effective_policy=effective_policy_from_json(effective_policy))
