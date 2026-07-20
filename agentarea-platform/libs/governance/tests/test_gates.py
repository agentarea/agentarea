"""Tests for gate interceptors."""

from uuid import uuid4

import pytest
from agentarea_governance.domain.enums import InterceptorAction, Phase
from agentarea_governance.domain.models import InterceptorContext
from agentarea_governance.interceptors.gates.cost_budget_guard import CostBudgetGuard
from agentarea_governance.interceptors.gates.service_budget_guard import ServiceBudgetGuard
from agentarea_governance.interceptors.gates.token_budget_guard import TokenBudgetGuard


def _ctx(
    action_name: str = "web_search", execution_state: dict | None = None
) -> InterceptorContext:
    return InterceptorContext(
        agent_id=uuid4(),
        workspace_id="ws-1",
        user_id="user-1",
        phase=Phase.PRE_TOOL_CALL,
        action_type="tool_call",
        action_name=action_name,
        execution_state=execution_state or {},
    )


class TestCostBudgetGuard:
    @pytest.mark.asyncio
    async def test_no_budget_allows(self):
        guard = CostBudgetGuard()
        result = await guard.execute(_ctx())
        assert result.action == InterceptorAction.ALLOW

    @pytest.mark.asyncio
    async def test_within_budget(self):
        guard = CostBudgetGuard()
        ctx = _ctx(execution_state={"budget_usd": 10.0, "cost_used": 3.0})
        result = await guard.execute(ctx)
        assert result.action == InterceptorAction.ALLOW

    @pytest.mark.asyncio
    async def test_warning_threshold(self):
        guard = CostBudgetGuard(warning_threshold=0.8)
        ctx = _ctx(execution_state={"budget_usd": 10.0, "cost_used": 8.5})
        result = await guard.execute(ctx)
        assert result.action == InterceptorAction.WARN
        assert "85%" in result.reason

    @pytest.mark.asyncio
    async def test_budget_exhausted(self):
        guard = CostBudgetGuard()
        ctx = _ctx(execution_state={"budget_usd": 10.0, "cost_used": 10.0})
        result = await guard.execute(ctx)
        assert result.action == InterceptorAction.DENY
        assert "exhausted" in result.reason

    @pytest.mark.asyncio
    async def test_over_budget(self):
        guard = CostBudgetGuard()
        ctx = _ctx(execution_state={"budget_usd": 10.0, "cost_used": 12.0})
        result = await guard.execute(ctx)
        assert result.action == InterceptorAction.DENY


class TestTokenBudgetGuard:
    @pytest.mark.asyncio
    async def test_no_budget_allows(self):
        guard = TokenBudgetGuard()
        result = await guard.execute(_ctx())
        assert result.action == InterceptorAction.ALLOW

    @pytest.mark.asyncio
    async def test_within_budget(self):
        guard = TokenBudgetGuard()
        ctx = _ctx(execution_state={"max_tokens": 100000, "tokens_used": 50000})
        result = await guard.execute(ctx)
        assert result.action == InterceptorAction.ALLOW

    @pytest.mark.asyncio
    async def test_warning_threshold(self):
        guard = TokenBudgetGuard(warning_threshold=0.85)
        ctx = _ctx(execution_state={"max_tokens": 100000, "tokens_used": 90000})
        result = await guard.execute(ctx)
        assert result.action == InterceptorAction.WARN

    @pytest.mark.asyncio
    async def test_budget_exhausted(self):
        guard = TokenBudgetGuard()
        ctx = _ctx(execution_state={"max_tokens": 100000, "tokens_used": 100000})
        result = await guard.execute(ctx)
        assert result.action == InterceptorAction.DENY
        assert "exhausted" in result.reason


class TestServiceBudgetGuard:
    @pytest.mark.asyncio
    async def test_no_budget_allows(self):
        guard = ServiceBudgetGuard()
        result = await guard.execute(_ctx())
        assert result.action == InterceptorAction.ALLOW
        assert "no service budget" in result.reason

    @pytest.mark.asyncio
    async def test_zero_budget_allows(self):
        guard = ServiceBudgetGuard()
        ctx = _ctx(execution_state={"service_budget_usd": 0})
        result = await guard.execute(ctx)
        assert result.action == InterceptorAction.ALLOW

    @pytest.mark.asyncio
    async def test_within_budget(self):
        guard = ServiceBudgetGuard()
        ctx = _ctx(execution_state={"service_budget_usd": 5.0, "service_cost_used": 1.0})
        result = await guard.execute(ctx)
        assert result.action == InterceptorAction.ALLOW
        assert "service budget ok" in result.reason

    @pytest.mark.asyncio
    async def test_warning_threshold(self):
        guard = ServiceBudgetGuard(warning_threshold=0.8)
        ctx = _ctx(execution_state={"service_budget_usd": 5.0, "service_cost_used": 4.5})
        result = await guard.execute(ctx)
        assert result.action == InterceptorAction.WARN
        assert "90%" in result.reason

    @pytest.mark.asyncio
    async def test_budget_exhausted(self):
        guard = ServiceBudgetGuard()
        ctx = _ctx(execution_state={"service_budget_usd": 5.0, "service_cost_used": 5.0})
        result = await guard.execute(ctx)
        assert result.action == InterceptorAction.DENY
        assert "exhausted" in result.reason
        assert result.metadata["service_cost_used"] == 5.0
        assert result.metadata["service_budget_usd"] == 5.0

    @pytest.mark.asyncio
    async def test_over_budget(self):
        guard = ServiceBudgetGuard()
        ctx = _ctx(execution_state={"service_budget_usd": 5.0, "service_cost_used": 7.0})
        result = await guard.execute(ctx)
        assert result.action == InterceptorAction.DENY
