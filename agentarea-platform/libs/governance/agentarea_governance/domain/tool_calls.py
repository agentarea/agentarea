"""Canonical tool-call metering semantics shared by execution runtimes."""

from __future__ import annotations

from collections.abc import Iterable

# Terminal control flow does not execute a capability and therefore must not
# consume the quota reserved for agent/tool work.
UNMETERED_TOOL_CALL_NAMES = frozenset({"completion", "task_complete"})


def metered_tool_call_count(tool_names: Iterable[str]) -> int:
    """Count calls that consume the governed tool-call quota."""
    return sum(name not in UNMETERED_TOOL_CALL_NAMES for name in tool_names)
