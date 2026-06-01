"""Tests for governance policy repositories."""

from uuid import uuid4

import pytest
from agentarea_common.auth.context import UserContext
from agentarea_common.base.models import BaseModel
from agentarea_governance.domain.policies import (
    BudgetPolicy,
    EffectivePolicy,
    PolicyDocument,
    PolicyScopeType,
)
from agentarea_governance.infrastructure.orm import (
    GovernancePolicyORM,
    TaskPolicySnapshotORM,
)
from agentarea_governance.infrastructure.repository import (
    GovernancePolicyRepository,
    TaskPolicySnapshotRepository,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: BaseModel.metadata.create_all(
                sync_conn,
                tables=[GovernancePolicyORM.__table__, TaskPolicySnapshotORM.__table__],
            )
        )
    try:
        yield async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    finally:
        await engine.dispose()


def _context(workspace_id: str) -> UserContext:
    return UserContext(user_id=f"user-{workspace_id}", workspace_id=workspace_id)


async def test_governance_policy_upsert_is_workspace_scoped(session_factory):
    async with session_factory() as session:
        repo_a = GovernancePolicyRepository(session, _context("workspace-a"))
        repo_b = GovernancePolicyRepository(session, _context("workspace-b"))

        await repo_a.upsert_scope_policy(
            scope_type=PolicyScopeType.WORKSPACE,
            scope_id="workspace-a",
            document=PolicyDocument(budget=BudgetPolicy(monthly_spend_cap_usd="10.00")),
        )

        assert await repo_a.get_scope_policy(
            scope_type=PolicyScopeType.WORKSPACE,
            scope_id="workspace-a",
        )
        assert await repo_b.get_scope_policy(
            scope_type=PolicyScopeType.WORKSPACE,
            scope_id="workspace-a",
        ) is None


async def test_governance_policy_upsert_updates_same_scope_kind(session_factory):
    async with session_factory() as session:
        repo = GovernancePolicyRepository(session, _context("workspace-a"))

        first_id, _ = await repo.upsert_scope_policy(
            scope_type=PolicyScopeType.WORKSPACE,
            scope_id="workspace-a",
            document=PolicyDocument(budget=BudgetPolicy(monthly_spend_cap_usd="10.00")),
        )
        second_id, updated = await repo.upsert_scope_policy(
            scope_type=PolicyScopeType.WORKSPACE,
            scope_id="workspace-a",
            document=PolicyDocument(budget=BudgetPolicy(monthly_spend_cap_usd="5.00")),
        )

        assert second_id == first_id
        assert str(updated.budget.monthly_spend_cap_usd) == "5.00"
        records = await repo.list_policies()
        assert len(records) == 1


async def test_task_policy_snapshot_is_immutable_per_task_kind(session_factory):
    task_id = uuid4()
    effective = EffectivePolicy(
        budget=BudgetPolicy(run_budget_usd="1.00"),
        source_policy_ids=["policy-1"],
    )

    async with session_factory() as session:
        repo = TaskPolicySnapshotRepository(session, _context("workspace-a"))
        await repo.create_snapshot(task_id=task_id, effective_policy=effective)

        loaded = await repo.get_snapshot(task_id=task_id)
        assert loaded is not None
        assert loaded.source_policy_ids == ["policy-1"]
        assert str(loaded.budget.run_budget_usd) == "1.00"

        with pytest.raises(ValueError, match="already exists"):
            await repo.create_snapshot(task_id=task_id, effective_policy=effective)
