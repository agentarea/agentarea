"""Parameter Object for tool invocations.

Replaces the loose collection of primitives (``workspace_id``, ``user_id``,
``workflow_id``, ``base_prefix``, …) that toolsets currently take as
individual constructor kwargs. The activity layer — the one place that
knows the calling Temporal task — builds a single
:class:`ToolInvocationContext` and hands it to whichever toolsets need it.
Toolsets that don't care simply ignore the field. New context fields land
here, never at the call site.

Why a frozen dataclass and not a contextvar / module-global:
    - explicit dependency, type-checkable
    - safe to use across ``asyncio.gather`` (each tool instance carries
      its own context, no thread-of-execution surprises)
    - tool instances are constructed per-activity, so the lifetime of
      the context is naturally bounded by the activity it was built for
    - extending with new fields (deadline, trace id, …) doesn't require
      touching every toolset's constructor signature
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ToolInvocationContext:
    """Immutable execution context handed to a toolset at construction time.

    Fields default to empty strings rather than ``None`` so toolsets can
    do truthy checks (``if ctx.workflow_id:``) without a None-guard.
    """

    workflow_id: str = ""
    task_id: str = ""
    workspace_id: str = ""
    user_id: str = ""
    agent_id: str = ""
    metadata: dict[str, str] = field(default_factory=dict)


_EMPTY = ToolInvocationContext()


def empty_context() -> ToolInvocationContext:
    """Return the canonical "no context" instance for tests / standalone use."""
    return _EMPTY
