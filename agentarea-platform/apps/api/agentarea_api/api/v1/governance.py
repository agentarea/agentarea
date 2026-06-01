"""Governance policy API endpoints."""

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
    PolicyScopeType,
    PolicyValidationError,
)
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/governance", tags=["governance"])

DatabaseSessionDep = Annotated[AsyncSession, Depends(get_db_session)]


class PolicyUpsertRequest(BaseModel):
    """Request body for creating or updating a source policy."""

    model_config = ConfigDict(extra="forbid")

    document: PolicyDocument
    enabled: bool = True
    parent_agent_id: UUID | None = Field(
        default=None,
        description="Required when validating a task-scoped persisted policy against its agent.",
    )


class PolicyResponse(BaseModel):
    id: str
    scope_type: PolicyScopeType
    scope_id: str
    enabled: bool
    document: PolicyDocument


class EffectivePolicyResponse(BaseModel):
    effective_policy: EffectivePolicy


class EffectivePolicyPreviewRequest(BaseModel):
    """Body for dry-run effective-policy resolution."""

    model_config = ConfigDict(extra="forbid")

    agent_id: UUID | None = None
    task_policy: PolicyDocument | None = None


def _parse_scope_type(scope_type: str) -> PolicyScopeType:
    try:
        return PolicyScopeType(scope_type)
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail=f"Unsupported policy scope: {scope_type}"
        ) from exc


def _policy_response(record) -> PolicyResponse:
    return PolicyResponse(
        id=record.id,
        scope_type=PolicyScopeType(record.scope_type),
        scope_id=record.scope_id,
        enabled=record.enabled,
        document=record.document,
    )


@router.get("/policies", response_model=list[PolicyResponse])
async def list_policies(
    user_context: UserContextDep,
    db_session: DatabaseSessionDep,
    scope_type: str | None = None,
    scope_id: str | None = None,
    enabled: bool | None = True,
) -> list[PolicyResponse]:
    """List source policies in the current workspace."""
    parsed_scope = _parse_scope_type(scope_type) if scope_type is not None else None
    service = GovernancePolicyService(RepositoryFactory(db_session, user_context))
    records = await service.list_policies(
        scope_type=parsed_scope,
        scope_id=scope_id,
        enabled=enabled,
    )
    return [_policy_response(record) for record in records]


@router.get("/policies/{scope_type}/{scope_id}", response_model=PolicyResponse)
async def get_policy(
    scope_type: str,
    scope_id: str,
    user_context: UserContextDep,
    db_session: DatabaseSessionDep,
) -> PolicyResponse:
    """Read one source policy in the current workspace."""
    parsed_scope = _parse_scope_type(scope_type)
    service = GovernancePolicyService(RepositoryFactory(db_session, user_context))
    record = await service.get_policy(
        scope_type=parsed_scope,
        scope_id=scope_id,
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Policy not found")
    return _policy_response(record)


@router.put("/policies/{scope_type}/{scope_id}", response_model=PolicyResponse)
async def upsert_policy(
    scope_type: str,
    scope_id: str,
    payload: PolicyUpsertRequest,
    user_context: UserContextDep,
    db_session: DatabaseSessionDep,
) -> PolicyResponse:
    """Create or update a source policy, rejecting obvious lower-scope loosening."""
    parsed_scope = _parse_scope_type(scope_type)
    service = GovernancePolicyService(RepositoryFactory(db_session, user_context))
    try:
        record = await service.upsert_policy(
            scope_type=parsed_scope,
            scope_id=scope_id,
            document=payload.document,
            enabled=payload.enabled,
            parent_agent_id=payload.parent_agent_id,
        )
    except PolicyValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return _policy_response(record)


@router.post("/effective-policy/preview", response_model=EffectivePolicyResponse)
async def preview_effective_policy(
    payload: EffectivePolicyPreviewRequest,
    user_context: UserContextDep,
    db_session: DatabaseSessionDep,
) -> EffectivePolicyResponse:
    """Compute effective policy without persisting a snapshot.

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
