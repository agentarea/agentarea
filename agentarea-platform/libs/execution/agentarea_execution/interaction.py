"""Supported human return routes, independent of workflow and model runtimes."""

from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Literal

#: How long a web chat's completed turn waits for the next message.
DEFAULT_FOLLOW_UP_WINDOW = timedelta(minutes=30)


@dataclass(frozen=True)
class InteractionCapabilities:
    channel: Literal["web", "none"] = "web"
    allow_questions: bool = True
    allow_approvals: bool = True
    allow_a2ui: bool = False


def resolve_interaction_capabilities(
    task_parameters: dict[str, Any],
    workflow_metadata: dict[str, Any],
    a2ui_enabled: bool,
) -> InteractionCapabilities:
    """Restrictions only subtract; an explicit web route can enable background runs."""
    interaction = task_parameters.get("interaction") or {}
    if not isinstance(interaction, dict):
        interaction = {"channel": "none"}
    if "channel" in interaction:
        web = interaction["channel"] == "web"
    elif task_parameters.get("delivery_address"):
        # Its replies go where the event came from, not to a person on the web.
        web = False
    else:
        sources = (
            task_parameters.get("source"),
            workflow_metadata.get("source"),
            workflow_metadata.get("created_via"),
        )
        started_by_schedule = bool(
            task_parameters.get("trigger_id")
            or task_parameters.get("trigger_type")
            or workflow_metadata.get("scheduled_at")
        )
        web = not started_by_schedule and all(
            source in (None, "", "web", "api", "rest", "manual") for source in sources
        )
    return InteractionCapabilities(
        channel="web" if web else "none",
        allow_questions=web and interaction.get("allow_questions", True) is True,
        allow_approvals=web and interaction.get("allow_approvals", True) is True,
        allow_a2ui=web and a2ui_enabled and interaction.get("allow_a2ui", True) is True,
    )


def follow_up_window(
    task_parameters: dict[str, Any], capabilities: InteractionCapabilities
) -> timedelta | None:
    """How long a completed turn waits for the next message, or None when it ends.

    A task in a session (one an event started) waits when the session continues,
    for its idle timeout; any other task waits when a person can answer it on the web.
    """
    session = task_parameters.get("session")
    if isinstance(session, dict):
        if session.get("continue") is not True:
            return None
        seconds = session.get("idle_timeout_seconds")
        if isinstance(seconds, int) and not isinstance(seconds, bool) and seconds > 0:
            return timedelta(seconds=seconds)
        return DEFAULT_FOLLOW_UP_WINDOW
    return DEFAULT_FOLLOW_UP_WINDOW if capabilities.channel == "web" else None
