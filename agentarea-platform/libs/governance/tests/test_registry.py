"""Tests for InterceptorRegistry."""

import logging

from agentarea_governance.domain.enums import (
    InterceptorAction,
    InterceptorCategory,
    Phase,
)
from agentarea_governance.domain.models import InterceptorContext, InterceptorResult
from agentarea_governance.registry import InterceptorRegistry


class FakeGate:
    def __init__(self, name: str = "fake_gate"):
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def category(self) -> InterceptorCategory:
        return InterceptorCategory.GATE

    async def execute(self, context: InterceptorContext) -> InterceptorResult:
        return InterceptorResult(
            action=InterceptorAction.ALLOW,
            interceptor_name=self._name,
            reason="ok",
        )


class TestInterceptorRegistry:
    def test_register_and_get(self):
        registry = InterceptorRegistry()
        gate = FakeGate()
        registry.register(gate, Phase.PRE_TOOL_CALL, priority=100)
        interceptors = registry.get_interceptors(Phase.PRE_TOOL_CALL)
        assert len(interceptors) == 1
        assert interceptors[0].name == "fake_gate"

    def test_empty_phase(self):
        registry = InterceptorRegistry()
        assert registry.get_interceptors(Phase.PRE_LLM_CALL) == []
        assert not registry.has_interceptors(Phase.PRE_LLM_CALL)

    def test_priority_ordering(self):
        registry = InterceptorRegistry()
        gate_a = FakeGate("a")
        gate_b = FakeGate("b")
        gate_c = FakeGate("c")
        registry.register(gate_c, Phase.PRE_TOOL_CALL, priority=300)
        registry.register(gate_a, Phase.PRE_TOOL_CALL, priority=100)
        registry.register(gate_b, Phase.PRE_TOOL_CALL, priority=200)
        interceptors = registry.get_interceptors(Phase.PRE_TOOL_CALL)
        assert [i.name for i in interceptors] == ["a", "b", "c"]

    def test_unregister(self):
        registry = InterceptorRegistry()
        gate = FakeGate("to_remove")
        registry.register(gate, Phase.PRE_TOOL_CALL, priority=100)
        assert registry.has_interceptors(Phase.PRE_TOOL_CALL)
        registry.unregister("to_remove", Phase.PRE_TOOL_CALL)
        assert not registry.has_interceptors(Phase.PRE_TOOL_CALL)

    def test_unregister_nonexistent(self):
        registry = InterceptorRegistry()
        registry.unregister("nonexistent", Phase.PRE_TOOL_CALL)

    def test_priority_collision_warning(self, caplog):
        registry = InterceptorRegistry()
        gate_a = FakeGate("a")
        gate_b = FakeGate("b")
        registry.register(gate_a, Phase.PRE_TOOL_CALL, priority=100)
        with caplog.at_level(logging.WARNING):
            registry.register(gate_b, Phase.PRE_TOOL_CALL, priority=100)
        assert "Priority collision" in caplog.text

    def test_different_phases_independent(self):
        registry = InterceptorRegistry()
        gate_a = FakeGate("a")
        gate_b = FakeGate("b")
        registry.register(gate_a, Phase.PRE_TOOL_CALL, priority=100)
        registry.register(gate_b, Phase.PRE_LLM_CALL, priority=100)
        assert len(registry.get_interceptors(Phase.PRE_TOOL_CALL)) == 1
        assert len(registry.get_interceptors(Phase.PRE_LLM_CALL)) == 1

    def test_callbacks_stored(self):
        registry = InterceptorRegistry()
        gate = FakeGate()
        on_deny = lambda r, c: None
        registry.register(gate, Phase.PRE_TOOL_CALL, priority=100, on_deny=on_deny)
        regs = registry.get_registrations(Phase.PRE_TOOL_CALL)
        assert len(regs) == 1
        assert regs[0].on_deny is on_deny
        assert regs[0].on_warn is None
