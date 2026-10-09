"""Tests for observer interceptors."""

import pytest
from uuid import uuid4

from agentarea_governance.domain.enums import InterceptorAction, Phase
from agentarea_governance.domain.models import InterceptorContext
from agentarea_governance.interceptors.observers.metrics_observer import MetricsObserver


def _ctx(
    action_name: str = "web_search",
    action_params: dict | None = None,
    content: str | None = None,
    execution_state: dict | None = None,
    phase: Phase = Phase.PRE_TOOL_CALL,
) -> InterceptorContext:
    return InterceptorContext(
        agent_id=uuid4(),
        workspace_id="ws-1",
        user_id="user-1",
        phase=phase,
        action_type="tool_call",
        action_name=action_name,
        action_params=action_params or {},
        content=content,
        execution_state=execution_state or {},
    )


# ── Observers ──


class TestMetricsObserver:
    @pytest.mark.asyncio
    async def test_records_counter(self):
        obs = MetricsObserver()
        await obs.execute(_ctx())
        assert obs.counters["pre_tool_call.tool_call"] == 1
        assert obs.counters["total.pre_tool_call"] == 1

    @pytest.mark.asyncio
    async def test_multiple_calls_increment(self):
        obs = MetricsObserver()
        await obs.execute(_ctx())
        await obs.execute(_ctx())
        assert obs.counters["pre_tool_call.tool_call"] == 2

    @pytest.mark.asyncio
    async def test_always_allows(self):
        obs = MetricsObserver()
        result = await obs.execute(_ctx())
        assert result.action == InterceptorAction.ALLOW

