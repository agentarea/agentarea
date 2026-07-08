"""Event visibility categories for multi-channel presentation."""

from typing import Final


class EventVisibility:
    """Categorize workflow events by audience relevance.

    Controls what events surface to each channel based on presentation mode.
    """

    # Final answer, errors — always shown
    RESULT: Final[set[str]] = {"WorkflowCompleted", "WorkflowFailed", "WorkflowCancelled"}

    # Agent needs human input — shown on interactive channels
    INTERACTION: Final[set[str]] = {
        "HumanApprovalRequested",
        "HumanApprovalReceived",
        "HumanInputRequested",
        "HumanInputReceived",
    }

    # Progress indicators — shown on concise channels
    STATUS: Final[set[str]] = {
        "WorkflowStarted",
        # Per-turn "working on it" marker. On persistent conversational
        # channels (Telegram/Slack) the workflow lives across turns, so
        # WorkflowStarted fires only once ever; WorkflowCommandReceived is
        # the per-message signal that seeds the live "⏳ Working..." frame
        # before the result edits it in place.
        "WorkflowCommandReceived",
        "ToolCallStarted",
        "AgentDelegationStarted",
        "AgentDelegationCompleted",
    }

    # Full detail — only webUI
    INTERNAL: Final[set[str]] = {
        "LLMCallStarted",
        "LLMCallChunk",
        "LLMCallCompleted",
        "LLMCallFailed",
        "ToolCallCompleted",
        "ToolCallFailed",
        "IterationCompleted",
        "ContextCompacted",
        "BudgetWarning",
        "BudgetExceeded",
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
    """Check if an event type should be shown for a given presentation mode."""
    visible_events = _VISIBILITY_MAP.get(presentation, _VISIBILITY_MAP[PresentationMode.CONCISE])
    return event_type in visible_events
