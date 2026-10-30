"""How hard a model reasons before it answers: an agent's setting, a run may override it.

Two forms: a level (``reasoning_effort``) or a token budget (``reasoning_max_tokens``),
at most one of them. Which levels a model takes is catalog data
(``reasoning_efforts`` on the model, else on its provider); with none stated the
value goes to the provider as given. Unset leaves the model at its own default.
"""

import re
from collections.abc import Sequence
from typing import Any

REASONING_EFFORT_PARAMETER = "reasoning_effort"
REASONING_MAX_TOKENS_PARAMETER = "reasoning_max_tokens"
_EFFORT_SHAPE = re.compile(r"^[a-z][a-z_-]{0,15}$")


def checked_reasoning_effort(value: Any) -> str | None:
    """``value`` as a reasoning level, None when unset; refused when it is not a level's shape."""
    if value is None or value == "":
        return None
    if not isinstance(value, str) or not _EFFORT_SHAPE.match(value):
        raise ValueError("reasoning_effort must be a level name such as low or high")
    return value


def checked_reasoning_max_tokens(value: Any) -> int | None:
    """``value`` as a reasoning token budget, None when unset; refused unless a positive integer."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("reasoning_max_tokens must be a positive integer")
    return value


def reasoning_effort_of(parameters: dict[str, Any] | None) -> str | None:
    """The reasoning level a task's parameters set, or None when they set none."""
    return checked_reasoning_effort((parameters or {}).get(REASONING_EFFORT_PARAMETER))


def reasoning_max_tokens_of(parameters: dict[str, Any] | None) -> int | None:
    """The reasoning token budget a task's parameters set, or None when they set none."""
    return checked_reasoning_max_tokens((parameters or {}).get(REASONING_MAX_TOKENS_PARAMETER))


def check_reasoning(parameters: dict[str, Any] | None) -> dict[str, Any] | None:
    """Field validator: refuse malformed reasoning parameters, or both forms at once."""
    if reasoning_effort_of(parameters) and reasoning_max_tokens_of(parameters):
        raise ValueError("set reasoning_effort or reasoning_max_tokens, not both")
    return parameters


def check_effort_supported(
    effort: str | None, levels: Sequence[str] | None, *, model_name: str
) -> None:
    """Refuse a level the catalog says this model does not take; no stated levels, no check."""
    if effort and levels and effort not in levels:
        raise ValueError(
            f"model {model_name} takes reasoning_effort {', '.join(levels)}, not {effort}"
        )


def reasoning_settings(
    parameters: dict[str, Any] | None, agent_effort: str | None, agent_max_tokens: int | None
) -> tuple[str | None, int | None]:
    """The level and budget a call asks for: a run that sets either replaces the agent's pair."""
    effort, max_tokens = reasoning_effort_of(parameters), reasoning_max_tokens_of(parameters)
    if effort or max_tokens:
        return effort, max_tokens
    return agent_effort, agent_max_tokens
