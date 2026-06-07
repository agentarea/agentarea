"""Tests for governance policy rule and snapshot repositories."""

from uuid import uuid4

import pytest
from agentarea_common.auth.context import UserContext
from agentarea_common.base.models import BaseModel
from agentarea_governance.domain.policies import (
    BudgetPolicy,
    EffectivePolicy,
)
from agentarea_governance.domain.rules import (
    PolicyEffect,
    PolicyRule,
    PolicySubjectType,
)
from agentarea_governance.infrastructure.orm import (
    PolicyRuleORM,
    TaskPolicySnapshotORM,
)
from agentarea_governance.infrastructure.repository import (
    PolicyRuleRepository,
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
                tables=[PolicyRuleORM.__table__, TaskPolicySnapshotORM.__table__],
            )
        )
    try:
        yield async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    finally:
        await engine.dispose()


def _context(workspace_id: str) -> UserContext:
    return UserContext(user_id=f"user-{workspace_id}", workspace_id=workspace_id)


def _rule(subject_id: str, target: str, effect: PolicyEffect, **params) -> PolicyRule:
    return PolicyRule(
        subject_type=PolicySubjectType.WORKSPACE,
        subject_id=subject_id,
        target=target,
        effect=effect,
        params=params,
    )


async def test_create_and_list_is_workspace_scoped(session_factory):
    async with session_factory() as session:
        repo_a = PolicyRuleRepository(session, _context("workspace-a"))
        repo_b = PolicyRuleRepository(session, _context("workspace-b"))

        await repo_a.create(
            _rule("workspace-a", "spend", PolicyEffect.CAP, amount_usd="10.00", period="month")
        )

        assert len(await repo_a.list_rules()) == 1
        assert await repo_b.list_rules() == []


async def test_list_filters(session_factory):
    async with session_factory() as session:
        repo = PolicyRuleRepository(session, _context("workspace-a"))
        await repo.create(_rule("workspace-a", "tool:a", PolicyEffect.DENY))
        await repo.create(_rule("workspace-a", "tool:b", PolicyEffect.ALLOW))

        denied = await repo.list_rules(effect=PolicyEffect.DENY)
        assert len(denied) == 1
        assert denied[0].target == "tool:a"

        by_target = await repo.list_rules(target="tool:b")
        assert len(by_target) == 1
        assert by_target[0].effect == PolicyEffect.ALLOW


async def test_get_update_set_enabled_delete(session_factory):
    async with session_factory() as session:
        repo = PolicyRuleRepository(session, _context("workspace-a"))
        created = await repo.create(_rule("workspace-a", "tool:x", PolicyEffect.DENY))

        loaded = await repo.get(created.id)
        assert loaded is not None
        assert loaded.target == "tool:x"

        updated = await repo.update(created.id, target="tool:y", priority=5)
        assert updated.target == "tool:y"
        assert updated.priority == 5

        toggled = await repo.set_enabled(created.id, False)
        assert toggled.enabled is False

        assert await repo.delete(created.id) is True
        assert await repo.get(created.id) is None
        assert await repo.delete(created.id) is False


async def test_get_other_workspace_returns_none(session_factory):
    async with session_factory() as session:
        repo_a = PolicyRuleRepository(session, _context("workspace-a"))
        repo_b = PolicyRuleRepository(session, _context("workspace-b"))
        created = await repo_a.create(_rule("workspace-a", "tool:x", PolicyEffect.DENY))

        assert await repo_b.get(created.id) is None
        assert await repo_b.update(created.id, priority=9) is None
        assert await repo_b.delete(created.id) is False


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
