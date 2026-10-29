"""The ``model_override`` task parameter: run this task on another model of the workspace.

The agent's own model stays as it is. The value is a model instance id; whether
that instance exists, belongs to the workspace and is a chat model is checked
when the run builds its agent configuration.
"""

from typing import Any
from uuid import UUID

MODEL_OVERRIDE_PARAMETER = "model_override"


def model_override_of(parameters: dict[str, Any] | None) -> str | None:
    """The model instance id a task's parameters name, or None when they name none."""
    value = (parameters or {}).get(MODEL_OVERRIDE_PARAMETER)
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ValueError(f"{MODEL_OVERRIDE_PARAMETER} must be a model instance id")
    try:
        return str(UUID(value))
    except ValueError:
        raise ValueError(f"{MODEL_OVERRIDE_PARAMETER} must be a model instance id") from None


def check_model_override(parameters: dict[str, Any] | None) -> dict[str, Any] | None:
    """Field validator: refuse a ``model_override`` that is not a model instance id."""
    model_override_of(parameters)
    return parameters
