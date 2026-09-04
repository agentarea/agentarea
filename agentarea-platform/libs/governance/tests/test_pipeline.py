"""Tests for InterceptorPipeline."""

import pytest
from uuid import uuid4

from agentarea_governance.domain.enums import (
    InterceptorAction,
    InterceptorCategory,
    Phase,
)
from agentarea_governance.domain.models import InterceptorContext, InterceptorResult
from agentarea_governance.pipeline import InterceptorPipeline
from agentarea_governance.registry import InterceptorRegistry


def _make_context(**kwargs) -> InterceptorContext:
    defaults = dict(
        agent_id=uuid4(),
        workspace_id="ws-1",
        user_id="user-1",
        phase=Phase.PRE_TOOL_CALL,
        action_type="tool_call",
        action_name="web_search",
    )
    defaults.update(kwargs)
    return InterceptorContext(**defaults)


class _MockInterceptor:
    def __init__(
        self,
        name: str,
        category: InterceptorCategory,
        action: InterceptorAction = InterceptorAction.ALLOW,
        reason: str = "ok",
        modified_content: str | None = None,
        should_raise: bool = False,
    ):
        self._name = name
        self._category = category
        self._action = action
        self._reason = reason
        self._modified_content = modified_content
        self._should_raise = should_raise
        self.call_count = 0

    @property
    def name(self) -> str:
        return self._name

    @property
    def category(self) -> InterceptorCategory:
        return self._category

    async def execute(self, context: InterceptorContext) -> InterceptorResult:
        self.call_count += 1
        if self._should_raise:
            raise RuntimeError(f"{self._name} exploded")
        return InterceptorResult(
            action=self._action,
            interceptor_name=self._name,
            reason=self._reason,
            modified_content=self._modified_content,
        )


class TestPipelineEmptyPhase:
    @pytest.mark.asyncio
    async def test_empty_returns_allow(self):
        registry = InterceptorRegistry()
        pipeline = InterceptorPipeline(registry)
        result = await pipeline.run(Phase.PRE_TOOL_CALL, _make_context())
        assert result.action == InterceptorAction.ALLOW
        assert result.reason == "no interceptors registered"


class TestPipelineGates:
    @pytest.mark.asyncio
    async def test_gate_allow(self):
        registry = InterceptorRegistry()
        gate = _MockInterceptor("g1", InterceptorCategory.GATE, InterceptorAction.ALLOW)
        registry.register(gate, Phase.PRE_TOOL_CALL, priority=100)
        pipeline = InterceptorPipeline(registry)
        result = await pipeline.run(Phase.PRE_TOOL_CALL, _make_context())
        assert result.action == InterceptorAction.ALLOW

    @pytest.mark.asyncio
    async def test_gate_deny_short_circuits(self):
        registry = InterceptorRegistry()
        gate1 = _MockInterceptor("g1", InterceptorCategory.GATE, InterceptorAction.DENY, "blocked")
        gate2 = _MockInterceptor("g2", InterceptorCategory.GATE, InterceptorAction.ALLOW)
        registry.register(gate1, Phase.PRE_TOOL_CALL, priority=100)
        registry.register(gate2, Phase.PRE_TOOL_CALL, priority=200)
        pipeline = InterceptorPipeline(registry)
        result = await pipeline.run(Phase.PRE_TOOL_CALL, _make_context())
        assert result.action == InterceptorAction.DENY
        assert result.interceptor_name == "g1"
        assert gate2.call_count == 0

    @pytest.mark.asyncio
    async def test_gate_escalate_short_circuits(self):
        registry = InterceptorRegistry()
        gate = _MockInterceptor("g1", InterceptorCategory.GATE, InterceptorAction.ESCALATE)
        registry.register(gate, Phase.PRE_TOOL_CALL, priority=100)
        pipeline = InterceptorPipeline(registry)
        result = await pipeline.run(Phase.PRE_TOOL_CALL, _make_context())
        assert result.action == InterceptorAction.ESCALATE

    @pytest.mark.asyncio
    async def test_gate_warn_continues(self):
        registry = InterceptorRegistry()
        gate1 = _MockInterceptor("g1", InterceptorCategory.GATE, InterceptorAction.WARN)
        gate2 = _MockInterceptor("g2", InterceptorCategory.GATE, InterceptorAction.ALLOW)
        registry.register(gate1, Phase.PRE_TOOL_CALL, priority=100)
        registry.register(gate2, Phase.PRE_TOOL_CALL, priority=200)
        pipeline = InterceptorPipeline(registry)
        result = await pipeline.run(Phase.PRE_TOOL_CALL, _make_context())
        assert result.action == InterceptorAction.ALLOW
        assert gate2.call_count == 1


class TestPipelineFilters:
    @pytest.mark.asyncio
    async def test_filter_modify_chains_content(self):
        registry = InterceptorRegistry()
        f1 = _MockInterceptor(
            "f1", InterceptorCategory.FILTER,
            InterceptorAction.MODIFY, modified_content="step1",
        )
        f2 = _MockInterceptor(
            "f2", InterceptorCategory.FILTER,
            InterceptorAction.MODIFY, modified_content="step2",
        )
        registry.register(f1, Phase.POST_LLM_CALL, priority=100)
        registry.register(f2, Phase.POST_LLM_CALL, priority=200)
        pipeline = InterceptorPipeline(registry)
        ctx = _make_context(phase=Phase.POST_LLM_CALL, content="original")
        result = await pipeline.run(Phase.POST_LLM_CALL, ctx)
        assert result.action == InterceptorAction.MODIFY
        assert result.modified_content == "step2"

    @pytest.mark.asyncio
    async def test_filter_deny_short_circuits(self):
        registry = InterceptorRegistry()
        f1 = _MockInterceptor("f1", InterceptorCategory.FILTER, InterceptorAction.DENY)
        f2 = _MockInterceptor("f2", InterceptorCategory.FILTER, InterceptorAction.ALLOW)
        registry.register(f1, Phase.POST_LLM_CALL, priority=100)
        registry.register(f2, Phase.POST_LLM_CALL, priority=200)
        pipeline = InterceptorPipeline(registry)
        result = await pipeline.run(Phase.POST_LLM_CALL, _make_context(phase=Phase.POST_LLM_CALL))
        assert result.action == InterceptorAction.DENY
        assert f2.call_count == 0


class TestPipelineObservers:
    @pytest.mark.asyncio
    async def test_observer_error_ignored(self):
        registry = InterceptorRegistry()
        obs = _MockInterceptor(
            "obs", InterceptorCategory.OBSERVER, should_raise=True,
        )
        registry.register(obs, Phase.PRE_TOOL_CALL, priority=100)
        pipeline = InterceptorPipeline(registry)
        result = await pipeline.run(Phase.PRE_TOOL_CALL, _make_context())
        assert result.action == InterceptorAction.ALLOW
        assert obs.call_count == 1


class TestPipelineFailClosed:
    @pytest.mark.asyncio
    async def test_gate_exception_denies(self):
        registry = InterceptorRegistry()
        gate = _MockInterceptor("g1", InterceptorCategory.GATE, should_raise=True)
        registry.register(gate, Phase.PRE_TOOL_CALL, priority=100)
        pipeline = InterceptorPipeline(registry)
        result = await pipeline.run(Phase.PRE_TOOL_CALL, _make_context())
        assert result.action == InterceptorAction.DENY
        assert result.interceptor_name == "g1"

    @pytest.mark.asyncio
    async def test_gate_exception_short_circuits_and_denies_downstream_allow(self):
        registry = InterceptorRegistry()
        gate1 = _MockInterceptor("g1", InterceptorCategory.GATE, should_raise=True)
        gate2 = _MockInterceptor("g2", InterceptorCategory.GATE, InterceptorAction.ALLOW)
        registry.register(gate1, Phase.PRE_TOOL_CALL, priority=100)
        registry.register(gate2, Phase.PRE_TOOL_CALL, priority=200)
        pipeline = InterceptorPipeline(registry)
        result = await pipeline.run(Phase.PRE_TOOL_CALL, _make_context())
        assert result.action == InterceptorAction.DENY
        assert gate2.call_count == 0

    @pytest.mark.asyncio
    async def test_gate_exception_fires_on_deny_callback(self):
        registry = InterceptorRegistry()
        gate = _MockInterceptor("g1", InterceptorCategory.GATE, should_raise=True)
        callback_results = []
        registry.register(
            gate, Phase.PRE_TOOL_CALL, priority=100,
            on_deny=lambda r, c: callback_results.append(r.interceptor_name),
        )
        pipeline = InterceptorPipeline(registry)
        await pipeline.run(Phase.PRE_TOOL_CALL, _make_context())
        assert callback_results == ["g1"]

    @pytest.mark.asyncio
    async def test_filter_exception_denies(self):
        registry = InterceptorRegistry()
        filt = _MockInterceptor("f1", InterceptorCategory.FILTER, should_raise=True)
        registry.register(filt, Phase.POST_LLM_CALL, priority=100)
        pipeline = InterceptorPipeline(registry)
        result = await pipeline.run(
            Phase.POST_LLM_CALL, _make_context(phase=Phase.POST_LLM_CALL)
        )
        assert result.action == InterceptorAction.DENY
        assert result.interceptor_name == "f1"

    @pytest.mark.asyncio
    async def test_observer_exception_still_allows(self):
        """Observers must keep the OBSERVER-swallows-exceptions behavior."""
        registry = InterceptorRegistry()
        obs = _MockInterceptor("obs", InterceptorCategory.OBSERVER, should_raise=True)
        registry.register(obs, Phase.PRE_TOOL_CALL, priority=100)
        pipeline = InterceptorPipeline(registry)
        result = await pipeline.run(Phase.PRE_TOOL_CALL, _make_context())
        assert result.action == InterceptorAction.ALLOW


class TestPipelineMixed:
    @pytest.mark.asyncio
    async def test_mixed_categories_priority_order(self):
        registry = InterceptorRegistry()
        gate = _MockInterceptor("gate", InterceptorCategory.GATE, InterceptorAction.ALLOW)
        filt = _MockInterceptor(
            "filter", InterceptorCategory.FILTER,
            InterceptorAction.MODIFY, modified_content="filtered",
        )
        obs = _MockInterceptor("obs", InterceptorCategory.OBSERVER)
        registry.register(gate, Phase.PRE_TOOL_CALL, priority=100)
        registry.register(filt, Phase.PRE_TOOL_CALL, priority=200)
        registry.register(obs, Phase.PRE_TOOL_CALL, priority=300)
        pipeline = InterceptorPipeline(registry)
        ctx = _make_context(content="original")
        result = await pipeline.run(Phase.PRE_TOOL_CALL, ctx)
        assert gate.call_count == 1
        assert filt.call_count == 1
        assert obs.call_count == 1
        assert result.action == InterceptorAction.MODIFY
        assert result.modified_content == "filtered"


class TestPipelineCallbacks:
    @pytest.mark.asyncio
    async def test_on_deny_callback_fired(self):
        registry = InterceptorRegistry()
        gate = _MockInterceptor("g1", InterceptorCategory.GATE, InterceptorAction.DENY)
        callback_results = []
        registry.register(
            gate, Phase.PRE_TOOL_CALL, priority=100,
            on_deny=lambda r, c: callback_results.append(r.interceptor_name),
        )
        pipeline = InterceptorPipeline(registry)
        await pipeline.run(Phase.PRE_TOOL_CALL, _make_context())
        assert callback_results == ["g1"]

    @pytest.mark.asyncio
    async def test_on_warn_callback_fired(self):
        registry = InterceptorRegistry()
        gate = _MockInterceptor("g1", InterceptorCategory.GATE, InterceptorAction.WARN)
        callback_results = []
        registry.register(
            gate, Phase.PRE_TOOL_CALL, priority=100,
            on_warn=lambda r, c: callback_results.append(r.interceptor_name),
        )
        pipeline = InterceptorPipeline(registry)
        await pipeline.run(Phase.PRE_TOOL_CALL, _make_context())
        assert callback_results == ["g1"]
