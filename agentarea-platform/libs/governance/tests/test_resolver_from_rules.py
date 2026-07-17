"""Tests for GovernancePolicyResolver reading from unified rules.

Proves the safety invariant indirectly: rules compile per layer and reuse the
unchanged PolicyResolver, so monotonic merge + validation + escalation_rules all
keep behaving as before.
"""

from uuid import uuid4

import pytest
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.tool_authorization import (
    ToolAuthorizationAction,
    decide_tool_policy,
)
from agentarea_common.base.models import BaseModel
from agentarea_common.base.repository_factory import RepositoryFactory
from agentarea_governance.application import GovernancePolicyResolver
from agentarea_governance.domain.policies import (
    BudgetPolicy,
    PolicyDocument,
    PolicyValidationError,
)
from agentarea_governance.domain.rules import (
    PolicyEffect,
    PolicyRule,
    PolicySubjectType,
)
from agentarea_governance.infrastructure.orm import PolicyRuleORM
from agentarea_governance.infrastructure.repository import PolicyRuleRepository
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: BaseModel.metadata.create_all(
                sync_conn,
                tables=[PolicyRuleORM.__table__],
            )
        )
    try:
        yield async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    finally:
        await engine.dispose()


def _context(workspace_id: str = "ws-a") -> UserContext:
    return UserContext(user_id="user-a", workspace_id=workspace_id)


def _rule(subject_type, subject_id, target, effect, **params) -> PolicyRule:
    return PolicyRule(
        subject_type=subject_type,
        subject_id=subject_id,
        target=target,
        effect=effect,
        params=params,
    )


async def test_resolve_workspace_budget_cap(session_factory):
    async with session_factory() as session:
        context = _context()
        repo = PolicyRuleRepository(session, context)
        await repo.create(
            _rule(
                PolicySubjectType.WORKSPACE,
                context.workspace_id,
                "spend",
                PolicyEffect.CAP,
                amount_usd="50.00",
                period="month",
            )
        )

        resolver = GovernancePolicyResolver(RepositoryFactory(session, context))
        effective = await resolver.resolve(workspace_id=context.workspace_id)

        assert str(effective.budget.monthly_spend_cap_usd) == "50.00"
        assert len(effective.source_policy_ids) == 1


async def test_resolve_merges_workspace_and_agent_tighter_wins(session_factory):
    async with session_factory() as session:
        context = _context()
        agent_id = uuid4()
        repo = PolicyRuleRepository(session, context)
        await repo.create(
            _rule(
                PolicySubjectType.WORKSPACE,
                context.workspace_id,
                "spend",
                PolicyEffect.CAP,
                amount_usd="100.00",
                period="month",
            )
        )
        await repo.create(
            _rule(
                PolicySubjectType.AGENT,
                str(agent_id),
                "spend",
                PolicyEffect.CAP,
                amount_usd="25.00",
                period="month",
            )
        )

        resolver = GovernancePolicyResolver(RepositoryFactory(session, context))
        effective = await resolver.resolve(workspace_id=context.workspace_id, agent_id=agent_id)

        assert str(effective.budget.monthly_spend_cap_usd) == "25.00"


async def test_agent_scoped_approval_rule_reaches_the_pdp_verdict(session_factory):
    # The per-tool "requires approval" toggle in the agent editor becomes one of
    # these rows. Everything downstream already exists — this pins the whole
    # chain: rule -> snapshot -> the verdict the workflow gate acts on.
    async with session_factory() as session:
        context = _context()
        agent_id = uuid4()
        repo = PolicyRuleRepository(session, context)
        await repo.create(
            _rule(
                PolicySubjectType.WORKSPACE,
                context.workspace_id,
                "tool:shell",
                PolicyEffect.ALLOW,
            )
        )
        await repo.create(
            _rule(
                PolicySubjectType.AGENT,
                str(agent_id),
                "tool:shell",
                PolicyEffect.APPROVAL,
            )
        )

        resolver = GovernancePolicyResolver(RepositoryFactory(session, context))
        effective = await resolver.resolve(workspace_id=context.workspace_id, agent_id=agent_id)

        assert "shell" in effective.approval.escalation_rules
        assert (
            decide_tool_policy(effective.to_json_dict(), "shell").action
            is ToolAuthorizationAction.REQUIRE_APPROVAL
        )


async def test_disabling_the_rule_is_how_approval_is_waived(session_factory):
    # No dedicated opt-out field: the resolver reads enabled=True rules only, so
    # switching the row off removes the escalation. The engine is the opt-out.
    async with session_factory() as session:
        context = _context()
        agent_id = uuid4()
        repo = PolicyRuleRepository(session, context)
        rule = _rule(
            PolicySubjectType.AGENT,
            str(agent_id),
            "tool:shell",
            PolicyEffect.APPROVAL,
        )
        rule.enabled = False
        await repo.create(rule)

        resolver = GovernancePolicyResolver(RepositoryFactory(session, context))
        effective = await resolver.resolve(workspace_id=context.workspace_id, agent_id=agent_id)

        assert not (effective.approval.escalation_rules if effective.approval else [])


async def test_resolve_rejects_agent_loosening(session_factory):
    async with session_factory() as session:
        context = _context()
        agent_id = uuid4()
        repo = PolicyRuleRepository(session, context)
        await repo.create(
            _rule(
                PolicySubjectType.WORKSPACE,
                context.workspace_id,
                "spend",
                PolicyEffect.CAP,
                amount_usd="10.00",
                period="month",
            )
        )
        await repo.create(
            _rule(
                PolicySubjectType.AGENT,
                str(agent_id),
                "spend",
                PolicyEffect.CAP,
                amount_usd="100.00",
                period="month",
            )
        )

        resolver = GovernancePolicyResolver(RepositoryFactory(session, context))
        with pytest.raises(PolicyValidationError):
            await resolver.resolve(workspace_id=context.workspace_id, agent_id=agent_id)


async def test_resolve_approval_tool_in_escalation_rules(session_factory):
    async with session_factory() as session:
        context = _context()
        repo = PolicyRuleRepository(session, context)
        await repo.create(
            _rule(
                PolicySubjectType.WORKSPACE,
                context.workspace_id,
                "tool:send_email",
                PolicyEffect.APPROVAL,
            )
        )

        resolver = GovernancePolicyResolver(RepositoryFactory(session, context))
        effective = await resolver.resolve(workspace_id=context.workspace_id)

        # execution_state must carry the tool in escalation_rules so the runtime
        # helpers.policy_requires_approval keeps pausing on it.
        state = effective.to_execution_state()
        assert "send_email" in state["escalation_rules"]


async def test_resolve_with_tightening_task_policy(session_factory):
    async with session_factory() as session:
        context = _context()
        repo = PolicyRuleRepository(session, context)
        await repo.create(
            _rule(
                PolicySubjectType.WORKSPACE,
                context.workspace_id,
                "spend",
                PolicyEffect.CAP,
                amount_usd="100.00",
                period="month",
            )
        )

        resolver = GovernancePolicyResolver(RepositoryFactory(session, context))
        effective = await resolver.resolve(
            workspace_id=context.workspace_id,
            task_policy=PolicyDocument(budget=BudgetPolicy(monthly_spend_cap_usd="10.00")),
        )

        assert str(effective.budget.monthly_spend_cap_usd) == "10.00"


async def test_resolve_empty_when_no_rules(session_factory):
    async with session_factory() as session:
        context = _context()
        resolver = GovernancePolicyResolver(RepositoryFactory(session, context))
        effective = await resolver.resolve(workspace_id=context.workspace_id)
        assert effective.budget is None
        assert effective.source_policy_ids == []
