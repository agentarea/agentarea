"""Tests for domain models, enums, protocols, exceptions, and events."""

import pytest
from uuid import uuid4

from agentarea_governance.domain.enums import (
    InterceptorAction,
    InterceptorCategory,
    Phase,
)
from agentarea_governance.domain.models import (
    DetectionFinding,
    InterceptorContext,
    InterceptorResult,
)
from agentarea_governance.domain.exceptions import (
    EscalationRequired,
    GovernanceDenied,
    SecurityBlocked,
)
from agentarea_governance.domain.events import GovernanceViolation, SecurityFinding


class TestEnums:
    def test_interceptor_category_values(self):
        assert InterceptorCategory.GATE == "gate"
        assert InterceptorCategory.FILTER == "filter"
        assert InterceptorCategory.OBSERVER == "observer"
        assert len(InterceptorCategory) == 3

    def test_phase_values(self):
        assert Phase.PRE_LLM_CALL == "pre_llm_call"
        assert Phase.POST_LLM_CALL == "post_llm_call"
        assert Phase.PRE_TOOL_CALL == "pre_tool_call"
        assert Phase.POST_TOOL_CALL == "post_tool_call"
        assert Phase.PRE_DELEGATION == "pre_delegation"
        assert Phase.POST_DELEGATION == "post_delegation"
        assert Phase.TOOL_DISCOVERY == "tool_discovery"
        assert len(Phase) == 7

    def test_interceptor_action_values(self):
        assert InterceptorAction.ALLOW == "allow"
        assert InterceptorAction.DENY == "deny"
        assert InterceptorAction.WARN == "warn"
        assert InterceptorAction.ESCALATE == "escalate"
        assert InterceptorAction.MODIFY == "modify"
        assert len(InterceptorAction) == 5


class TestInterceptorContext:
    def test_construction(self):
        agent_id = uuid4()
        ctx = InterceptorContext(
            agent_id=agent_id,
            workspace_id="ws-1",
            user_id="user-1",
            phase=Phase.PRE_TOOL_CALL,
            action_type="tool_call",
            action_name="web_search",
        )
        assert ctx.agent_id == agent_id
        assert ctx.workspace_id == "ws-1"
        assert ctx.phase == Phase.PRE_TOOL_CALL
        assert ctx.content is None
        assert ctx.action_params == {}
        assert ctx.execution_state == {}

    def test_with_content(self):
        ctx = InterceptorContext(
            agent_id=uuid4(),
            workspace_id="ws-1",
            user_id="user-1",
            phase=Phase.POST_LLM_CALL,
            action_type="llm_call",
            action_name="model-1",
            content="Hello world",
        )
        assert ctx.content == "Hello world"


class TestDetectionFinding:
    def test_construction(self):
        finding = DetectionFinding(
            category="pii.email",
            matched_text="test@example.com",
            span=(10, 26),
            confidence=1.0,
            engine_name="regex",
        )
        assert finding.category == "pii.email"
        assert finding.confidence == 1.0
        assert finding.span == (10, 26)

    def test_frozen(self):
        finding = DetectionFinding(
            category="pii.email",
            matched_text="test@example.com",
            span=(0, 16),
            confidence=1.0,
            engine_name="regex",
        )
        with pytest.raises(AttributeError):
            finding.category = "other"  # type: ignore[misc]


class TestInterceptorResult:
    def test_allow_result(self):
        result = InterceptorResult(
            action=InterceptorAction.ALLOW,
            interceptor_name="test_guard",
            reason="all good",
        )
        assert result.action == InterceptorAction.ALLOW
        assert result.modified_content is None
        assert result.findings == []
        assert result.metadata == {}

    def test_modify_result(self):
        result = InterceptorResult(
            action=InterceptorAction.MODIFY,
            interceptor_name="sanitizer",
            reason="redacted PII",
            modified_content="Hello [REDACTED]",
            findings=[
                DetectionFinding(
                    category="pii.email",
                    matched_text="test@example.com",
                    span=(6, 22),
                    confidence=1.0,
                    engine_name="regex",
                )
            ],
        )
        assert result.modified_content == "Hello [REDACTED]"
        assert len(result.findings) == 1

    def test_frozen(self):
        result = InterceptorResult(
            action=InterceptorAction.ALLOW,
            interceptor_name="test",
            reason="ok",
        )
        with pytest.raises(AttributeError):
            result.action = InterceptorAction.DENY  # type: ignore[misc]


class TestExceptions:
    def test_governance_denied(self):
        exc = GovernanceDenied(
            reason="budget exceeded",
            interceptor_name="cost_budget_guard",
        )
        assert "cost_budget_guard" in str(exc)
        assert "budget exceeded" in str(exc)
        assert isinstance(exc, Exception)

    def test_security_blocked(self):
        exc = SecurityBlocked(
            reason="injection detected",
            interceptor_name="prompt_injection_detector",
        )
        assert "injection detected" in str(exc)
        assert isinstance(exc, Exception)

    def test_escalation_required(self):
        exc = EscalationRequired(
            reason="destructive action",
            interceptor_name="escalation_guard",
        )
        assert "destructive action" in str(exc)
        assert isinstance(exc, Exception)


class TestEvents:
    def test_governance_violation(self):
        event = GovernanceViolation(
            agent_id=uuid4(),
            workspace_id="ws-1",
            phase=Phase.PRE_TOOL_CALL,
            interceptor_name="capability_guard",
            action=InterceptorAction.DENY,
            reason="tool not allowed",
        )
        assert event.event_type == "governance.deny"
        assert event.interceptor_name == "capability_guard"
        assert event.event_id is not None
        assert event.timestamp is not None

    def test_security_finding(self):
        event = SecurityFinding(
            agent_id=uuid4(),
            workspace_id="ws-1",
            phase=Phase.POST_LLM_CALL,
            interceptor_name="output_sanitizer",
            finding_category="pii.email",
            confidence=0.95,
            engine_name="regex",
        )
        assert event.event_type == "security.finding.pii.email"
