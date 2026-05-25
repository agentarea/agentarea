"""Repositories for governance policies and task policy snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from agentarea_common.auth.context import UserContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.policies import (
    RESOLVER_VERSION,
    EffectivePolicy,
    PolicyDocument,
    PolicyScopeType,
    effective_policy_from_json,
    policy_from_json,
)
from .orm import GovernancePolicyORM, TaskPolicySnapshotORM


@dataclass(frozen=True)
class GovernancePolicyRecord:
    """Read model for a persisted source policy."""

    id: str
    scope_type: str
    scope_id: str
    document: PolicyDocument
    enabled: bool


class GovernancePolicyRepository:
    """Workspace-scoped repository for source governance policies."""

    def __init__(self, session: AsyncSession, user_context: UserContext):
        self.session = session
        self.user_context = user_context

    async def get_scope_policy(
        self,
        *,
        scope_type: PolicyScopeType | str,
        scope_id: str,
    ) -> tuple[str, PolicyDocument] | None:
        stmt = select(GovernancePolicyORM).where(
            GovernancePolicyORM.workspace_id == self.user_context.workspace_id,
            GovernancePolicyORM.scope_type == str(scope_type),
            GovernancePolicyORM.scope_id == scope_id,
            GovernancePolicyORM.enabled.is_(True),
        )
        result = await self.session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return str(row.id), policy_from_json(row.document)

    async def list_policies(
        self,
        *,
        scope_type: PolicyScopeType | str | None = None,
        scope_id: str | None = None,
        enabled: bool | None = None,
    ) -> list[GovernancePolicyRecord]:
        stmt = select(GovernancePolicyORM).where(
            GovernancePolicyORM.workspace_id == self.user_context.workspace_id
        )
        if scope_type is not None:
            stmt = stmt.where(GovernancePolicyORM.scope_type == str(scope_type))
        if scope_id is not None:
            stmt = stmt.where(GovernancePolicyORM.scope_id == scope_id)
        if enabled is not None:
            stmt = stmt.where(GovernancePolicyORM.enabled.is_(enabled))

        result = await self.session.execute(
            stmt.order_by(
                GovernancePolicyORM.scope_type,
                GovernancePolicyORM.scope_id,
            )
        )
        return [
            GovernancePolicyRecord(
                id=str(row.id),
                scope_type=row.scope_type,
                scope_id=row.scope_id,
                document=policy_from_json(row.document),
                enabled=row.enabled,
            )
            for row in result.scalars().all()
        ]

    async def get_chain(
        self,
        *,
        workspace_id: str,
        agent_id: UUID | str | None,
        task_id: UUID | str | None,
    ) -> tuple[list[str], list[PolicyDocument]]:
        source_ids: list[str] = []
        policies: list[PolicyDocument] = []
        scopes = [
            (PolicyScopeType.WORKSPACE, workspace_id),
            (PolicyScopeType.AGENT, str(agent_id) if agent_id else None),
            (PolicyScopeType.TASK, str(task_id) if task_id else None),
        ]
        for scope_type, scope_id in scopes:
            if not scope_id:
                continue
            found = await self.get_scope_policy(
                scope_type=scope_type, scope_id=scope_id
            )
            if found:
                source_id, policy = found
                source_ids.append(source_id)
                policies.append(policy)
        return source_ids, policies

    async def upsert_scope_policy(
        self,
        *,
        scope_type: PolicyScopeType | str,
        scope_id: str,
        document: PolicyDocument,
        enabled: bool = True,
    ) -> tuple[str, PolicyDocument]:
        workspace_id = self.user_context.workspace_id
        doc = document.to_json_dict()
        existing_stmt = select(GovernancePolicyORM).where(
            GovernancePolicyORM.workspace_id == workspace_id,
            GovernancePolicyORM.scope_type == str(scope_type),
            GovernancePolicyORM.scope_id == scope_id,
        )
        result = await self.session.execute(existing_stmt)
        row = result.scalar_one_or_none()
        if row is None:
            row = GovernancePolicyORM(
                workspace_id=workspace_id,
                created_by=self.user_context.user_id,
                scope_type=str(scope_type),
                scope_id=scope_id,
                document=doc,
                enabled=enabled,
            )
            self.session.add(row)
        else:
            row.document = doc
            row.enabled = enabled
            row.updated_at = datetime.now(UTC)

        await self.session.flush()
        return str(row.id), policy_from_json(row.document)


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
