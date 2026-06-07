"""Unified governance policy rule API endpoints."""

from typing import Annotated, Any
from uuid import UUID

from agentarea_common.auth import UserContextDep
from agentarea_common.base.repository_factory import RepositoryFactory
from agentarea_common.infrastructure.database import get_db_session
from agentarea_governance.application import GovernancePolicyService
from agentarea_governance.domain.rules import (
    PolicyEffect,
    PolicyRule,
    PolicySubjectType,
)
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/policies", tags=["policies"])

DatabaseSessionDep = Annotated[AsyncSession, Depends(get_db_session)]


class PolicyRuleResponse(BaseModel):
    """Serialized policy rule returned to clients."""

    id: str
    enabled: bool
    priority: int
    subject_type: PolicySubjectType
    subject_id: str
    target: str
    effect: PolicyEffect
    params: dict[str, Any]
    condition: str | None = None


class PolicyRuleCreateRequest(BaseModel):
    """Request body for creating a policy rule."""

    model_config = ConfigDict(extra="forbid")

    subject_type: PolicySubjectType
    subject_id: str
    target: str
    effect: PolicyEffect
    params: dict[str, Any] = Field(default_factory=dict)
    condition: str | None = None
    enabled: bool = True
    priority: int = 0


class PolicyRuleUpdateRequest(BaseModel):
    """Request body for partially updating a policy rule."""

    model_config = ConfigDict(extra="forbid")

    subject_type: PolicySubjectType | None = None
    subject_id: str | None = None
    target: str | None = None
    effect: PolicyEffect | None = None
    params: dict[str, Any] | None = None
    condition: str | None = None
    enabled: bool | None = None
    priority: int | None = None


def _rule_response(rule: PolicyRule) -> PolicyRuleResponse:
    return PolicyRuleResponse(
        id=rule.id or "",
        enabled=rule.enabled,
        priority=rule.priority,
        subject_type=rule.subject_type,
        subject_id=rule.subject_id,
        target=rule.target,
        effect=rule.effect,
        params=rule.params,
        condition=rule.condition,
    )


@router.get("", response_model=list[PolicyRuleResponse])
async def list_policy_rules(
    user_context: UserContextDep,
    db_session: DatabaseSessionDep,
    subject_type: PolicySubjectType | None = None,
    subject_id: str | None = None,
    effect: PolicyEffect | None = None,
    target: str | None = None,
    enabled: bool | None = None,
) -> list[PolicyRuleResponse]:
    """List policy rules in the current workspace."""
    service = GovernancePolicyService(RepositoryFactory(db_session, user_context))
    rules = await service.list_rules(
        subject_type=subject_type,
        subject_id=subject_id,
        effect=effect,
        target=target,
        enabled=enabled,
    )
    return [_rule_response(rule) for rule in rules]


@router.post("", response_model=PolicyRuleResponse, status_code=201)
async def create_policy_rule(
    payload: PolicyRuleCreateRequest,
    user_context: UserContextDep,
    db_session: DatabaseSessionDep,
) -> PolicyRuleResponse:
    """Create a policy rule in the current workspace."""
    service = GovernancePolicyService(RepositoryFactory(db_session, user_context))
    rule = PolicyRule(
        subject_type=payload.subject_type,
        subject_id=payload.subject_id,
        target=payload.target,
        effect=payload.effect,
        params=payload.params,
        condition=payload.condition,
        enabled=payload.enabled,
        priority=payload.priority,
    )
    created = await service.create_rule(rule=rule, subject_id=payload.subject_id)
    return _rule_response(created)


@router.get("/{rule_id}", response_model=PolicyRuleResponse)
async def get_policy_rule(
    rule_id: UUID,
    user_context: UserContextDep,
    db_session: DatabaseSessionDep,
) -> PolicyRuleResponse:
    """Read one policy rule in the current workspace."""
    service = GovernancePolicyService(RepositoryFactory(db_session, user_context))
    rule = await service.get_rule(rule_id=rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Policy rule not found")
    return _rule_response(rule)


@router.patch("/{rule_id}", response_model=PolicyRuleResponse)
async def update_policy_rule(
    rule_id: UUID,
    payload: PolicyRuleUpdateRequest,
    user_context: UserContextDep,
    db_session: DatabaseSessionDep,
) -> PolicyRuleResponse:
    """Partially update a policy rule."""
    service = GovernancePolicyService(RepositoryFactory(db_session, user_context))
    fields = payload.model_dump(exclude_unset=True)
    updated = await service.update_rule(rule_id=rule_id, **fields)
    if updated is None:
        raise HTTPException(status_code=404, detail="Policy rule not found")
    return _rule_response(updated)


@router.delete("/{rule_id}", status_code=204)
async def delete_policy_rule(
    rule_id: UUID,
    user_context: UserContextDep,
    db_session: DatabaseSessionDep,
) -> Response:
    """Delete a policy rule."""
    service = GovernancePolicyService(RepositoryFactory(db_session, user_context))
    deleted = await service.delete_rule(rule_id=rule_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Policy rule not found")
    return Response(status_code=204)
