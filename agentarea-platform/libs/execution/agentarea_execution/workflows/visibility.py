"""Event visibility categories for multi-channel presentation."""

from typing import Final

from agentarea_common.events.contract import canonical_type


class EventVisibility:
    """Categorize workflow events by audience relevance.

    Controls what events surface to each channel based on presentation mode.
    Members come from the closed vocabulary in agentarea_common.events.contract.
    """

    # Final answer, errors — always shown
    RESULT: Final[set[str]] = {"task.completed", "task.failed", "task.cancelled"}

    # Agent needs human input — shown on interactive channels
    INTERACTION: Final[set[str]] = {
        "approval.requested",
        "approval.decided",
        "input.request",
        "input.response",
    }

    # Progress indicators — shown on concise channels
    STATUS: Final[set[str]] = {
        "task.started",
        # Per-turn "working on it" marker. On persistent conversational
        # channels (Telegram/Slack) the workflow lives across turns, so
        # task.started fires only once ever; command.received is the
        # per-message signal that seeds the live "Working..." frame before
        # the result edits it in place.
        "command.received",
        "tool.call",
        "delegation.started",
        "delegation.completed",
    }

    # Full detail — only webUI
    INTERNAL: Final[set[str]] = {
        "llm.call.started",
        "llm.call.chunk",
        "llm.call.completed",
        "llm.call.failed",
        "tool.result",
        "turn.completed",
        "context.compacted",
        "budget.warning",
        "budget.exceeded",
    }


class PresentationMode:
    """Presentation modes for channels."""

    VERBOSE = "verbose"  # Everything (webUI)
    CONCISE = "concise"  # result + interaction + status (Telegram, Slack)
    SUMMARY = "summary"  # result + interaction (email — batched at end)
    SILENT = "silent"  # result only (system-to-system)


# Mapping: presentation mode → visible event categories
_VISIBILITY_MAP: dict[str, set[str]] = {
    PresentationMode.VERBOSE: (
        EventVisibility.RESULT
        | EventVisibility.INTERACTION
        | EventVisibility.STATUS
        | EventVisibility.INTERNAL
    ),
    PresentationMode.CONCISE: (
        EventVisibility.RESULT | EventVisibility.INTERACTION | EventVisibility.STATUS
    ),
    PresentationMode.SUMMARY: EventVisibility.RESULT | EventVisibility.INTERACTION,
    PresentationMode.SILENT: EventVisibility.RESULT,
}


def is_visible(event_type: str, presentation: str) -> bool:
    """Check if an event type should be shown for a given presentation mode.

    ``canonical_type`` only strips a defensive ``workflow.`` prefix.
    """
    visible_events = _VISIBILITY_MAP.get(presentation, _VISIBILITY_MAP[PresentationMode.CONCISE])
    return canonical_type(event_type) in visible_events
