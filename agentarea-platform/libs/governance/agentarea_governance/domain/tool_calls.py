"""Canonical tool-call semantics shared by execution runtimes."""

from __future__ import annotations

from collections.abc import Iterable

# Terminal control flow: it ends the run, so it cannot be repeated to spend
# quota, and charging the agent for saying it is finished would be nonsense.
# This is the only exemption from the governed tool-call budget.
UNMETERED_TOOL_CALL_NAMES = frozenset({"completion", "task_complete"})

# Control flow that can be repeated. Each dispatches a real activity and a turn
# may carry any number of them, so they stay metered even though policy never
# gates them.
_REPEATABLE_CONTROL_FLOW_TOOL_NAMES = frozenset(
    {
        "request_user_input",
        "recall_history",
        "read_tool_output",
        "activate_tool_source",
        "activate_skill",
        "load_tools",
    }
)

# Workflow control flow, not capabilities: these reach no external system, so
# policy never gates them on execution and they stay offered under a
# deny-by-default policy. Without completion the agent can never finish, without
# request_user_input it can never ask, and without the discovery tools it cannot
# see what else it has. Disclosure and metering are different questions, so the
# unmetered set is a subset of this one by construction rather than by
# coincidence — the two can drift only if someone edits this line.
CONTROL_FLOW_TOOL_NAMES = UNMETERED_TOOL_CALL_NAMES | _REPEATABLE_CONTROL_FLOW_TOOL_NAMES


def metered_tool_call_count(tool_names: Iterable[str]) -> int:
    """Count calls that consume the governed tool-call quota."""
    return sum(name not in UNMETERED_TOOL_CALL_NAMES for name in tool_names)
