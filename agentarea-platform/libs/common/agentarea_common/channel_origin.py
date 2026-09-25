"""The task parameter that routes a run's replies out through a channel trigger.

``channel_origin`` names the trigger whose bot credentials outbound delivery
uses. Only the trigger service builds it, from the trigger that received the
event, so every surface that accepts caller-written parameters refuses it.
"""

from typing import Any

CHANNEL_ORIGIN_PARAMETER = "channel_origin"


def reject_channel_origin(parameters: dict[str, Any] | None) -> dict[str, Any] | None:
    if parameters and CHANNEL_ORIGIN_PARAMETER in parameters:
        raise ValueError(
            f"{CHANNEL_ORIGIN_PARAMETER} is set by the trigger that received the event "
            "and cannot be supplied"
        )
    return parameters


def drop_channel_origin(parameters: dict[str, Any] | None) -> dict[str, Any] | None:
    """For an edit: parameters stored before the check echo the key back from the form."""
    if parameters and CHANNEL_ORIGIN_PARAMETER in parameters:
        return {k: v for k, v in parameters.items() if k != CHANNEL_ORIGIN_PARAMETER}
    return parameters
