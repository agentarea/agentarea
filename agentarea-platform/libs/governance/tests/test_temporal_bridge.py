"""Tests for the Temporal bridge adapter."""

import pytest
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from agentarea_governance.bridges.temporal_bridge import (
    GovernanceActivityInterceptor,
    GovernanceWorkerInterceptor,
    _ACTIVITY_PHASE_MAP,
    _extract_context_from_input,
    _resolve_action_type,
    validate_activity_mapping,
)
from agentarea_governance.domain.enums import (
    InterceptorAction,
    InterceptorCategory,
    Phase,
)
from agentarea_governance.domain.exceptions import EscalationRequired, GovernanceDenied
from agentarea_governance.domain.models import InterceptorContext, InterceptorResult
from agentarea_governance.interceptors.gates.capability_guard import CapabilityGuard
from agentarea_governance.interceptors.gates.cost_budget_guard import CostBudgetGuard
from agentarea_governance.pipeline import InterceptorPipeline
from agentarea_governance.registry import InterceptorRegistry


class _MockInterceptor:
    def __init__(
        self,
        name: str = "mock",
        category: InterceptorCategory = InterceptorCategory.GATE,
        action: InterceptorAction = InterceptorAction.ALLOW,
        reason: str = "ok",
        modified_content: str | None = None,
    ):
        self._name = name
        self._category = category
        self._action = action
        self._reason = reason
        self._modified_content = modified_content
        self.call_count = 0
        self.last_context: InterceptorContext | None = None

    @property
    def name(self) -> str:
        return self._name

    @property
    def category(self) -> InterceptorCategory:
        return self._category

    async def execute(self, context: InterceptorContext) -> InterceptorResult:
        self.call_count += 1
        self.last_context = context
        return InterceptorResult(
            action=self._action,
            interceptor_name=self._name,
            reason=self._reason,
            modified_content=self._modified_content,
        )


# Fake Temporal types for testing without full Temporal dependency
@dataclass
class _FakeActivityInput:
    fn: Any
    args: list[Any]


class _FakeNextInterceptor:
    def __init__(self, return_value: Any = "activity_result"):
        self.return_value = return_value
        self.called = False

    async def execute_activity(self, input: Any) -> Any:
        self.called = True
        return self.return_value


@dataclass
class _FakeLLMCallRequest:
    messages: list[dict[str, Any]]
    model_id: str
    workspace_id: str = "ws-1"
    agent_id: str = ""
    user_context_data: dict[str, Any] | None = None
    effective_policy: dict[str, Any] | None = None
    cost_used: float | None = None
    tokens_used: int | None = None
    service_cost_used: float | None = None

    def model_dump(self) -> dict[str, Any]:
        return {"messages": self.messages, "model_id": self.model_id}


@dataclass
class _FakeMCPToolRequest:
    tool_name: str
    tool_args: dict[str, Any]
    workspace_id: str = "ws-1"
    user_context_data: dict[str, Any] | None = None
    effective_policy: dict[str, Any] | None = None
    cost_used: float | None = None
    tokens_used: int | None = None
    service_cost_used: float | None = None

    def model_dump(self) -> dict[str, Any]:
        return {"tool_name": self.tool_name, "tool_args": self.tool_args}


@dataclass
class _FakeLLMResult:
    content: str = "Hello world"


def _make_fn(name: str):
    async def fn():
        pass
    fn.__name__ = name
    return fn


class TestActivityPhaseMapping:
    def test_llm_activity_mapped(self):
        assert "call_llm_activity" in _ACTIVITY_PHASE_MAP
        pre, post = _ACTIVITY_PHASE_MAP["call_llm_activity"]
        assert pre == Phase.PRE_LLM_CALL
        assert post == Phase.POST_LLM_CALL

    def test_tool_activity_mapped(self):
        assert "execute_mcp_tool_activity" in _ACTIVITY_PHASE_MAP
        pre, post = _ACTIVITY_PHASE_MAP["execute_mcp_tool_activity"]
        assert pre == Phase.PRE_TOOL_CALL
        assert post == Phase.POST_TOOL_CALL

    def test_discovery_activity_mapped(self):
        pre, post = _ACTIVITY_PHASE_MAP["discover_available_tools_activity"]
        assert pre is None
        assert post == Phase.TOOL_DISCOVERY

    def test_unknown_activity_not_mapped(self):
        assert "publish_workflow_events_activity" not in _ACTIVITY_PHASE_MAP


class TestResolveActionType:
    def test_llm_call(self):
        assert _resolve_action_type("call_llm_activity") == "llm_call"

    def test_tool_call(self):
        assert _resolve_action_type("execute_mcp_tool_activity") == "tool_call"

    def test_discovery(self):
        assert _resolve_action_type("discover_available_tools_activity") == "tool_discovery"

    def test_unknown(self):
        assert _resolve_action_type("some_custom_activity") == "some_custom_activity"


class TestContextExtraction:
    def test_extract_from_llm_request(self):
        request = _FakeLLMCallRequest(
            messages=[{"role": "user", "content": "hi"}],
            model_id="gpt-4",
            workspace_id="ws-1",
            agent_id=str(uuid4()),
        )
        fn = _make_fn("call_llm_activity")
        input = _FakeActivityInput(fn=fn, args=[request])
        context = _extract_context_from_input(input, Phase.PRE_LLM_CALL)
        assert context is not None
        assert context.workspace_id == "ws-1"
        assert context.action_type == "llm_call"
        assert context.action_name == "gpt-4"

    def test_extract_from_mcp_request(self):
        request = _FakeMCPToolRequest(
            tool_name="web_search",
            tool_args={"query": "test"},
            workspace_id="ws-2",
        )
        fn = _make_fn("execute_mcp_tool_activity")
        input = _FakeActivityInput(fn=fn, args=[request])
        context = _extract_context_from_input(input, Phase.PRE_TOOL_CALL)
        assert context is not None
        assert context.action_name == "web_search"
        assert context.action_type == "tool_call"
        assert context.action_params == {"query": "test"}

    def test_extract_with_no_args(self):
        fn = _make_fn("call_llm_activity")
        input = _FakeActivityInput(fn=fn, args=[])
        context = _extract_context_from_input(input, Phase.PRE_LLM_CALL)
        assert context is None


class TestExecutionStateFromPolicy:
    def test_policy_populates_execution_state(self):
        request = _FakeLLMCallRequest(
            messages=[{"role": "user", "content": "hi"}],
            model_id="gpt-4",
            effective_policy={
                "budget": {"run_budget_usd": "10.00"},
                "tools": {"allowed": ["web_*"], "denied": []},
            },
            cost_used=4.0,
            tokens_used=1200,
        )
        fn = _make_fn("call_llm_activity")
        input = _FakeActivityInput(fn=fn, args=[request])
        context = _extract_context_from_input(input, Phase.PRE_LLM_CALL)
        assert context is not None
        assert context.execution_state["budget_usd"] == 10.0
        assert context.execution_state["cost_used"] == 4.0
        assert context.execution_state["tokens_used"] == 1200
        assert context.execution_state["tools_config"]["allowed"] == ["web_*"]

    def test_no_policy_leaves_state_empty(self):
        request = _FakeLLMCallRequest(messages=[], model_id="gpt-4")
        fn = _make_fn("call_llm_activity")
        input = _FakeActivityInput(fn=fn, args=[request])
        context = _extract_context_from_input(input, Phase.PRE_LLM_CALL)
        assert context is not None
        assert context.execution_state == {}

    @pytest.mark.asyncio
    async def test_budget_policy_denies_when_exhausted(self):
        registry = InterceptorRegistry()
        registry.register(CostBudgetGuard(), Phase.PRE_LLM_CALL, priority=100)
        pipeline = InterceptorPipeline(registry)
        next_interceptor = _FakeNextInterceptor()
        bridge = GovernanceActivityInterceptor(next_interceptor, pipeline)
        request = _FakeLLMCallRequest(
            messages=[],
            model_id="gpt-4",
            effective_policy={"budget": {"run_budget_usd": "10.00"}},
            cost_used=10.0,
        )
        input = _FakeActivityInput(fn=_make_fn("call_llm_activity"), args=[request])
        with pytest.raises(GovernanceDenied):
            await bridge.execute_activity(input)
        assert not next_interceptor.called

    @pytest.mark.asyncio
    async def test_capability_policy_denies_disallowed_tool(self):
        registry = InterceptorRegistry()
        registry.register(CapabilityGuard(), Phase.PRE_TOOL_CALL, priority=200)
        pipeline = InterceptorPipeline(registry)
        next_interceptor = _FakeNextInterceptor()
        bridge = GovernanceActivityInterceptor(next_interceptor, pipeline)
        request = _FakeMCPToolRequest(
            tool_name="shell_exec",
            tool_args={},
            effective_policy={"tools": {"allowed": ["web_*"], "denied": []}},
        )
        input = _FakeActivityInput(fn=_make_fn("execute_mcp_tool_activity"), args=[request])
        with pytest.raises(GovernanceDenied):
            await bridge.execute_activity(input)
        assert not next_interceptor.called


class TestGovernanceActivityInterceptor:
    @pytest.mark.asyncio
    async def test_unmapped_activity_passes_through(self):
        registry = InterceptorRegistry()
        pipeline = InterceptorPipeline(registry)
        next_interceptor = _FakeNextInterceptor("result")
        bridge = GovernanceActivityInterceptor(next_interceptor, pipeline)
        fn = _make_fn("publish_workflow_events_activity")
        input = _FakeActivityInput(fn=fn, args=[])
        result = await bridge.execute_activity(input)
        assert result == "result"
        assert next_interceptor.called

    @pytest.mark.asyncio
    async def test_empty_registry_passes_through(self):
        registry = InterceptorRegistry()
        pipeline = InterceptorPipeline(registry)
        next_interceptor = _FakeNextInterceptor("result")
        bridge = GovernanceActivityInterceptor(next_interceptor, pipeline)
        request = _FakeLLMCallRequest(
            messages=[{"role": "user", "content": "hi"}],
            model_id="gpt-4",
        )
        fn = _make_fn("call_llm_activity")
        input = _FakeActivityInput(fn=fn, args=[request])
        result = await bridge.execute_activity(input)
        assert result == "result"

    @pytest.mark.asyncio
    async def test_gate_deny_raises(self):
        registry = InterceptorRegistry()
        gate = _MockInterceptor("denier", InterceptorCategory.GATE, InterceptorAction.DENY, "blocked")
        registry.register(gate, Phase.PRE_LLM_CALL, priority=100)
        pipeline = InterceptorPipeline(registry)
        next_interceptor = _FakeNextInterceptor()
        bridge = GovernanceActivityInterceptor(next_interceptor, pipeline)
        request = _FakeLLMCallRequest(
            messages=[{"role": "user", "content": "hi"}],
            model_id="gpt-4",
        )
        fn = _make_fn("call_llm_activity")
        input = _FakeActivityInput(fn=fn, args=[request])
        with pytest.raises(GovernanceDenied) as exc_info:
            await bridge.execute_activity(input)
        assert "blocked" in str(exc_info.value)
        assert not next_interceptor.called

    @pytest.mark.asyncio
    async def test_gate_escalate_raises(self):
        registry = InterceptorRegistry()
        gate = _MockInterceptor("escalator", InterceptorCategory.GATE, InterceptorAction.ESCALATE, "needs human")
        registry.register(gate, Phase.PRE_TOOL_CALL, priority=100)
        pipeline = InterceptorPipeline(registry)
        next_interceptor = _FakeNextInterceptor()
        bridge = GovernanceActivityInterceptor(next_interceptor, pipeline)
        request = _FakeMCPToolRequest(tool_name="delete_all", tool_args={})
        fn = _make_fn("execute_mcp_tool_activity")
        input = _FakeActivityInput(fn=fn, args=[request])
        with pytest.raises(EscalationRequired):
            await bridge.execute_activity(input)

    @pytest.mark.asyncio
    async def test_post_phase_filter_modifies_output(self):
        registry = InterceptorRegistry()
        filt = _MockInterceptor(
            "sanitizer", InterceptorCategory.FILTER,
            InterceptorAction.MODIFY, "ok", modified_content="[REDACTED]",
        )
        registry.register(filt, Phase.POST_LLM_CALL, priority=100)
        pipeline = InterceptorPipeline(registry)
        next_interceptor = _FakeNextInterceptor(_FakeLLMResult(content="secret data"))
        bridge = GovernanceActivityInterceptor(next_interceptor, pipeline)
        request = _FakeLLMCallRequest(
            messages=[{"role": "user", "content": "hi"}],
            model_id="gpt-4",
        )
        fn = _make_fn("call_llm_activity")
        input = _FakeActivityInput(fn=fn, args=[request])
        result = await bridge.execute_activity(input)
        assert result.content == "[REDACTED]"


class TestGovernanceWorkerInterceptor:
    def test_creates_activity_interceptor(self):
        registry = InterceptorRegistry()
        pipeline = InterceptorPipeline(registry)
        worker_interceptor = GovernanceWorkerInterceptor(pipeline)
        next_interceptor = _FakeNextInterceptor()
        activity_interceptor = worker_interceptor.intercept_activity(next_interceptor)
        assert isinstance(activity_interceptor, GovernanceActivityInterceptor)


class TestStartupValidation:
    def test_all_activities_present(self, caplog):
        activities = ["call_llm_activity", "execute_mcp_tool_activity", "discover_available_tools_activity"]
        with caplog.at_level("WARNING"):
            validate_activity_mapping(activities)
        assert "not registered" not in caplog.text

    def test_missing_activity_warns(self, caplog):
        activities = ["call_llm_activity"]
        with caplog.at_level("WARNING"):
            validate_activity_mapping(activities)
        assert "execute_mcp_tool_activity" in caplog.text
