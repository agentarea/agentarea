"""Task parameters only the trigger that received an event may write.

``channel_origin`` names the trigger whose bot credentials outbound delivery
uses; ``follow_up_message`` is what a follow-up into a running conversation
delivers; ``trigger_event`` and ``trigger_event_file`` are the event a run
writes into its own inputs. The trigger service builds them from the event, so
every surface that accepts caller-written parameters refuses them.
"""

from typing import Any

from .trigger_event_file import TRIGGER_EVENT_FILE_PARAMETER, TRIGGER_EVENT_PARAMETER

CHANNEL_ORIGIN_PARAMETER = "channel_origin"

# What a follow-up routed into a running conversation delivers: the person's own
# message, not the full first-run message built around it.
FOLLOW_UP_MESSAGE_PARAMETER = "follow_up_message"

RESERVED_TASK_PARAMETERS = frozenset(
    {
        CHANNEL_ORIGIN_PARAMETER,
        FOLLOW_UP_MESSAGE_PARAMETER,
        TRIGGER_EVENT_PARAMETER,
        TRIGGER_EVENT_FILE_PARAMETER,
    }
)


def reject_reserved_parameters(parameters: dict[str, Any] | None) -> dict[str, Any] | None:
    reserved = sorted(RESERVED_TASK_PARAMETERS.intersection(parameters or {}))
    if reserved:
        raise ValueError(
            f"{', '.join(reserved)} is set by the trigger that received the event "
            "and cannot be supplied"
        )
    return parameters


def drop_reserved_parameters(parameters: dict[str, Any] | None) -> dict[str, Any] | None:
    """For an edit: parameters stored before the check echo the keys back from the form."""
    if parameters and RESERVED_TASK_PARAMETERS.intersection(parameters):
        return {k: v for k, v in parameters.items() if k not in RESERVED_TASK_PARAMETERS}
    return parameters
