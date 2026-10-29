"""How hard a model reasons before it answers: an agent's setting, a run may override it.

The value goes to the provider in the form its API expects (``reasoning_effort``
or ``reasoning.effort``, see ``ProviderProfile.reasoning_param``). Unset leaves the
model at its own default.
"""

from typing import Any

REASONING_EFFORT_PARAMETER = "reasoning_effort"
REASONING_EFFORTS = ("minimal", "low", "medium", "high")


def checked_reasoning_effort(value: Any) -> str | None:
    """``value`` as a reasoning effort, None when unset; anything else is refused."""
    if value is None or value == "":
        return None
    if value not in REASONING_EFFORTS:
        raise ValueError(f"reasoning_effort must be one of {', '.join(REASONING_EFFORTS)}")
    return value


def reasoning_effort_of(parameters: dict[str, Any] | None) -> str | None:
    """The reasoning effort a task's parameters set, or None when they set none."""
    return checked_reasoning_effort((parameters or {}).get(REASONING_EFFORT_PARAMETER))


def check_reasoning_effort(parameters: dict[str, Any] | None) -> dict[str, Any] | None:
    """Field validator: refuse a ``reasoning_effort`` parameter outside the known values."""
    reasoning_effort_of(parameters)
    return parameters
