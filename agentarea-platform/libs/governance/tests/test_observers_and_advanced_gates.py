"""Tests for observer interceptors and advanced gate interceptors."""

import pytest
from uuid import uuid4

from agentarea_governance.domain.enums import InterceptorAction, Phase
from agentarea_governance.domain.models import InterceptorContext
from agentarea_governance.interceptors.observers.metrics_observer import MetricsObserver
from agentarea_governance.interceptors.observers.audit_observer import AuditObserver
from agentarea_governance.interceptors.gates.semantic_guard import SemanticGuard
from agentarea_governance.interceptors.gates.escalation_guard import EscalationGuard


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


class TestAuditObserver:
    @pytest.mark.asyncio
    async def test_without_sink(self):
        obs = AuditObserver()
        result = await obs.execute(_ctx())
        assert result.action == InterceptorAction.ALLOW

    @pytest.mark.asyncio
    async def test_with_sink(self):
        published = []

        class FakeSink:
            async def publish(self, event):
                published.append(event)

        obs = AuditObserver(event_sink=FakeSink())
        await obs.execute(_ctx())
        assert len(published) == 1

    @pytest.mark.asyncio
    async def test_sink_failure_handled(self):
        class FailingSink:
            async def publish(self, event):
                raise ConnectionError("sink down")

        obs = AuditObserver(event_sink=FailingSink())
        result = await obs.execute(_ctx())
        assert result.action == InterceptorAction.ALLOW


# ── Semantic Guard ──


class TestSemanticGuard:
    @pytest.mark.asyncio
    async def test_safe_call(self):
        guard = SemanticGuard()
        result = await guard.execute(
            _ctx(action_params={"query": "SELECT * FROM users WHERE id = 1"})
        )
        assert result.action == InterceptorAction.ALLOW

    @pytest.mark.asyncio
    async def test_drop_table_denied(self):
        guard = SemanticGuard()
        result = await guard.execute(
            _ctx(action_params={"query": "DROP TABLE users"})
        )
        assert result.action == InterceptorAction.DENY
        assert "DROP TABLE" in result.reason

    @pytest.mark.asyncio
    async def test_rm_rf_root_denied(self):
        guard = SemanticGuard()
        result = await guard.execute(
            _ctx(action_params={"command": "rm -rf /"})
        )
        assert result.action == InterceptorAction.DENY

    @pytest.mark.asyncio
    async def test_delete_from_escalated(self):
        guard = SemanticGuard()
        result = await guard.execute(
            _ctx(action_params={"query": "DELETE FROM orders WHERE status = 'cancelled'"})
        )
        assert result.action == InterceptorAction.ESCALATE
        assert "DELETE FROM" in result.reason

    @pytest.mark.asyncio
    async def test_no_content(self):
        guard = SemanticGuard()
        result = await guard.execute(_ctx())
        assert result.action == InterceptorAction.ALLOW

    @pytest.mark.asyncio
    async def test_content_field_checked(self):
        guard = SemanticGuard()
        result = await guard.execute(
            _ctx(content="TRUNCATE TABLE logs")
        )
        assert result.action == InterceptorAction.DENY


# ── Escalation Guard ──


class TestEscalationGuard:
    @pytest.mark.asyncio
    async def test_no_rules_allows(self):
        guard = EscalationGuard()
        result = await guard.execute(_ctx())
        assert result.action == InterceptorAction.ALLOW

    @pytest.mark.asyncio
    async def test_matching_rule_escalates(self):
        guard = EscalationGuard()
        ctx = _ctx(
            action_name="payment_process",
            execution_state={"escalation_rules": ["payment_*", "delete_*"]},
        )
        result = await guard.execute(ctx)
        assert result.action == InterceptorAction.ESCALATE
        assert "payment_process" in result.reason

    @pytest.mark.asyncio
    async def test_no_match_allows(self):
        guard = EscalationGuard()
        ctx = _ctx(
            action_name="web_search",
            execution_state={"escalation_rules": ["payment_*"]},
        )
        result = await guard.execute(ctx)
        assert result.action == InterceptorAction.ALLOW

    @pytest.mark.asyncio
    async def test_matched_rules_in_metadata(self):
        guard = EscalationGuard()
        ctx = _ctx(
            action_name="delete_user",
            execution_state={"escalation_rules": ["payment_*", "delete_*"]},
        )
        result = await guard.execute(ctx)
        assert result.action == InterceptorAction.ESCALATE
        assert "delete_*" in result.metadata["matched_rules"]
