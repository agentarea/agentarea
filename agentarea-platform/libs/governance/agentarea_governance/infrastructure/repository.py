"""Repositories for governance policy rules and task policy snapshots."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from agentarea_common.auth.context import UserContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.policies import (
    RESOLVER_VERSION,
    EffectivePolicy,
    effective_policy_from_json,
)
from ..domain.rules import PolicyEffect, PolicyRule, PolicySubjectType
from .orm import PolicyRuleORM, TaskPolicySnapshotORM


def _to_rule(row: PolicyRuleORM) -> PolicyRule:
    return PolicyRule(
        id=str(row.id),
        enabled=row.enabled,
        priority=row.priority,
        subject_type=PolicySubjectType(row.subject_type),
        subject_id=row.subject_id,
        target=row.target,
        effect=PolicyEffect(row.effect),
        params=row.params or {},
        condition=row.condition,
    )


class PolicyRuleRepository:
    """Workspace-scoped repository for unified governance policy rules."""

    def __init__(self, session: AsyncSession, user_context: UserContext):
        self.session = session
        self.user_context = user_context

    async def list_rules(
        self,
        *,
        subject_type: PolicySubjectType | str | None = None,
        subject_id: str | None = None,
        effect: PolicyEffect | str | None = None,
        target: str | None = None,
        enabled: bool | None = None,
    ) -> list[PolicyRule]:
        stmt = select(PolicyRuleORM).where(
            PolicyRuleORM.workspace_id == self.user_context.workspace_id
        )
        if subject_type is not None:
            stmt = stmt.where(PolicyRuleORM.subject_type == str(subject_type))
        if subject_id is not None:
            stmt = stmt.where(PolicyRuleORM.subject_id == subject_id)
        if effect is not None:
            stmt = stmt.where(PolicyRuleORM.effect == str(effect))
        if target is not None:
            stmt = stmt.where(PolicyRuleORM.target == target)
        if enabled is not None:
            stmt = stmt.where(PolicyRuleORM.enabled.is_(enabled))

        result = await self.session.execute(
            stmt.order_by(
                PolicyRuleORM.subject_type,
                PolicyRuleORM.subject_id,
                PolicyRuleORM.priority,
            )
        )
        return [_to_rule(row) for row in result.scalars().all()]

    async def get(self, rule_id: UUID | str) -> PolicyRule | None:
        row = await self._get_row(rule_id)
        return _to_rule(row) if row is not None else None

    async def create(self, rule: PolicyRule) -> PolicyRule:
        row = PolicyRuleORM(
            workspace_id=self.user_context.workspace_id,
            created_by=self.user_context.user_id,
            subject_type=str(rule.subject_type),
            subject_id=rule.subject_id,
            target=rule.target,
            effect=str(rule.effect),
            params=rule.params or {},
            condition=rule.condition,
            enabled=rule.enabled,
            priority=rule.priority,
        )
        self.session.add(row)
        await self.session.flush()
        return _to_rule(row)

    async def update(self, rule_id: UUID | str, **fields) -> PolicyRule | None:
        row = await self._get_row(rule_id)
        if row is None:
            return None

        allowed = {
            "subject_type",
            "subject_id",
            "target",
            "effect",
            "params",
            "condition",
            "enabled",
            "priority",
        }
        for key, value in fields.items():
            if value is None or key not in allowed:
                continue
            if key in ("subject_type", "effect"):
                value = str(value)
            setattr(row, key, value)
        row.updated_at = datetime.now(UTC)
        await self.session.flush()
        return _to_rule(row)

    async def set_enabled(self, rule_id: UUID | str, enabled: bool) -> PolicyRule | None:
        row = await self._get_row(rule_id)
        if row is None:
            return None
        row.enabled = enabled
        row.updated_at = datetime.now(UTC)
        await self.session.flush()
        return _to_rule(row)

    async def delete(self, rule_id: UUID | str) -> bool:
        row = await self._get_row(rule_id)
        if row is None:
            return False
        await self.session.delete(row)
        await self.session.flush()
        return True

    async def _get_row(self, rule_id: UUID | str) -> PolicyRuleORM | None:
        try:
            rule_uuid = rule_id if isinstance(rule_id, UUID) else UUID(str(rule_id))
        except (ValueError, AttributeError):
            return None
        stmt = select(PolicyRuleORM).where(
            PolicyRuleORM.workspace_id == self.user_context.workspace_id,
            PolicyRuleORM.id == rule_uuid,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()


class TaskPolicySnapshotRepository:
    """Workspace-scoped repository for immutable effective policy snapshots."""

    def __init__(self, session: AsyncSession, user_context: UserContext):
        self.session = session
        self.user_context = user_context

    async def create_snapshot(
        self,
        *,
        task_id: UUID | str,
        effective_policy: EffectivePolicy,
    ) -> EffectivePolicy:
        existing = await self.get_snapshot(task_id=task_id)
        if existing is not None:
            raise ValueError("task policy snapshot already exists")

        row = TaskPolicySnapshotORM(
            workspace_id=self.user_context.workspace_id,
            created_by=self.user_context.user_id,
            task_id=str(task_id),
            effective_policy=effective_policy.to_json_dict(),
            source_policy_ids=effective_policy.source_policy_ids,
            resolver_version=effective_policy.resolver_version or RESOLVER_VERSION,
            resolved_at=datetime.now(UTC).replace(tzinfo=None),
        )
        self.session.add(row)
        await self.session.flush()
        return effective_policy

    async def get_snapshot(
        self,
        *,
        task_id: UUID | str,
    ) -> EffectivePolicy | None:
        stmt = select(TaskPolicySnapshotORM).where(
            TaskPolicySnapshotORM.workspace_id == self.user_context.workspace_id,
            TaskPolicySnapshotORM.task_id == str(task_id),
        )
        result = await self.session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return effective_policy_from_json(row.effective_policy)
