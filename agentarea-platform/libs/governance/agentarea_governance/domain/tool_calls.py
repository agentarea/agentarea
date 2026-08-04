"""Canonical tool-call metering semantics shared by execution runtimes."""

from __future__ import annotations

from collections.abc import Iterable

# Workflow control flow, not capabilities: these tools reach no external system,
# so they are never policy-gated on execution and never consume the quota
# reserved for agent/tool work. Disclosure and metering read the same set, which
# is what keeps a tool from being offered under a deny-by-default policy and then
# billed against a budget it was never meant to touch.
CONTROL_FLOW_TOOL_NAMES = frozenset(
    {
        "completion",
        "task_complete",
        "request_user_input",
        "recall_history",
        "read_tool_output",
        "activate_tool_source",
        "load_tools",
    }
)


def metered_tool_call_count(tool_names: Iterable[str]) -> int:
    """Count calls that consume the governed tool-call quota."""
    return sum(name not in CONTROL_FLOW_TOOL_NAMES for name in tool_names)
