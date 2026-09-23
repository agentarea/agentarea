"""Supported human return routes, independent of workflow and model runtimes."""

from dataclasses import dataclass
from typing import Any, Literal


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
    origin = task_parameters.get("channel_origin")
    if "channel" in interaction:
        web = interaction["channel"] == "web"
    elif origin:
        web = isinstance(origin, dict) and origin.get("type") == "web"
    else:
        sources = (
            task_parameters.get("source"),
            workflow_metadata.get("source"),
            workflow_metadata.get("created_via"),
        )
        web = not (
            task_parameters.get("trigger_id")
            or task_parameters.get("trigger_type")
            or workflow_metadata.get("scheduled_at")
        )
        web = web and all(
            source in (None, "", "web", "api", "rest", "manual") for source in sources
        )
    return InteractionCapabilities(
        channel="web" if web else "none",
        allow_questions=web and interaction.get("allow_questions", True) is True,
        allow_approvals=web and interaction.get("allow_approvals", True) is True,
        allow_a2ui=web and a2ui_enabled and interaction.get("allow_a2ui", True) is True,
    )
