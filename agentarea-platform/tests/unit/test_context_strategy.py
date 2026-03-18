"""Unit tests for ContextStrategy enum and guard functions."""


from agentarea_execution.workflows.context_strategy import (
    ContextStrategy,
    allows_history_preservation,
    allows_output_offloading,
    allows_tool_progressive_disclosure,
    resolve_context_strategy,
)


class TestContextStrategyEnum:
    def test_values(self):
        assert ContextStrategy.STATIC.value == "static"
        assert ContextStrategy.HYBRID.value == "hybrid"
        assert ContextStrategy.DYNAMIC.value == "dynamic"

    def test_is_string_enum(self):
        assert isinstance(ContextStrategy.STATIC, str)
        assert ContextStrategy.HYBRID == "hybrid"


class TestResolveContextStrategy:
    def test_defaults_to_hybrid(self):
        assert resolve_context_strategy(None, None) == ContextStrategy.HYBRID

    def test_agent_override_takes_priority(self):
        result = resolve_context_strategy("dynamic", "static")
        assert result == ContextStrategy.DYNAMIC

    def test_model_default_when_no_agent_override(self):
        result = resolve_context_strategy(None, "static")
        assert result == ContextStrategy.STATIC

    def test_invalid_value_falls_back_to_hybrid(self):
        result = resolve_context_strategy("invalid", None)
        assert result == ContextStrategy.HYBRID

    def test_all_valid_values(self):
        for val in ("static", "hybrid", "dynamic"):
            result = resolve_context_strategy(val, None)
            assert result == ContextStrategy(val)


class TestAllowsOutputOffloading:
    def test_static_off(self):
        assert allows_output_offloading(ContextStrategy.STATIC) is False

    def test_hybrid_on(self):
        assert allows_output_offloading(ContextStrategy.HYBRID) is True

    def test_dynamic_on(self):
        assert allows_output_offloading(ContextStrategy.DYNAMIC) is True


class TestAllowsToolProgressiveDisclosure:
    def test_static_off(self):
        assert allows_tool_progressive_disclosure(ContextStrategy.STATIC) is False

    def test_hybrid_off(self):
        assert allows_tool_progressive_disclosure(ContextStrategy.HYBRID) is False

    def test_dynamic_on(self):
        assert allows_tool_progressive_disclosure(ContextStrategy.DYNAMIC) is True


class TestAllowsHistoryPreservation:
    def test_static_off(self):
        assert allows_history_preservation(ContextStrategy.STATIC) is False

    def test_hybrid_on(self):
        assert allows_history_preservation(ContextStrategy.HYBRID) is True

    def test_dynamic_on(self):
        assert allows_history_preservation(ContextStrategy.DYNAMIC) is True
