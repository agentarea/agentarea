"""Context strategy for dynamic context discovery.

Controls how aggressively the workflow offloads context to MinIO
based on model capabilities.
"""

from enum import StrEnum


class ContextStrategy(StrEnum):
    """Context management strategy for agent execution.

    STATIC: Current behavior — all tools loaded, full outputs in context.
    HYBRID: Offload large outputs to MinIO, but keep all tools loaded. Default.
    DYNAMIC: Full progressive disclosure — lazy tool loading + offloaded outputs.
    """

    STATIC = "static"
    HYBRID = "hybrid"
    DYNAMIC = "dynamic"


def resolve_context_strategy(
    agent_strategy: str | None,
    model_strategy: str | None,
) -> ContextStrategy:
    """Resolve context strategy from agent override and model default.

    Resolution order: agent override > model default > "hybrid".
    """
    raw = agent_strategy or model_strategy or "hybrid"
    try:
        return ContextStrategy(raw)
    except ValueError:
        return ContextStrategy.HYBRID


def allows_output_offloading(strategy: ContextStrategy) -> bool:
    """Whether to offload large tool outputs to MinIO."""
    return strategy in (ContextStrategy.HYBRID, ContextStrategy.DYNAMIC)


def allows_tool_progressive_disclosure(strategy: ContextStrategy) -> bool:
    """Whether to use lazy MCP tool loading (catalog + activate)."""
    return strategy == ContextStrategy.DYNAMIC


def allows_history_preservation(strategy: ContextStrategy) -> bool:
    """Whether to save full message history to MinIO before compaction."""
    return strategy in (ContextStrategy.HYBRID, ContextStrategy.DYNAMIC)
