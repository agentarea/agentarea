"""The model each LLM condition of a trigger is evaluated with.

An LLM condition names its own model instance (``model_id``); there is no
default to fall back on. A chat model reads the condition as a prompt, a
decision model answers it as a yes/no question; no other kind can.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, Protocol
from uuid import UUID

from agentarea_llm.domain.model_kind import ModelKind

from .domain.enums import ConditionType
from .logging_utils import TriggerValidationError

CONDITION_MODEL_KINDS = (ModelKind.CHAT, ModelKind.DECISION)


class ModelInstances(Protocol):
    async def get_by_id(self, id: UUID) -> Any: ...


def is_llm_condition(condition: dict[str, Any]) -> bool:
    """An explicit ``llm`` condition, or an untyped one the evaluator reads as one."""
    kind = condition.get("type")
    return kind == ConditionType.LLM or (kind is None and "description" in condition)


def llm_conditions(conditions: dict[str, Any] | None) -> Iterator[dict[str, Any]]:
    """Every LLM condition in ``conditions``, through nested combined conditions."""
    if not isinstance(conditions, dict):
        return
    if conditions.get("type") == ConditionType.COMBINED:
        for sub_condition in conditions.get("conditions") or []:
            yield from llm_conditions(sub_condition)
    elif is_llm_condition(conditions):
        yield conditions


async def validate_condition_models(
    conditions: dict[str, Any] | None, instances: ModelInstances
) -> None:
    """Refuse an LLM condition whose model is missing, foreign, or of a kind that cannot answer."""
    for condition in llm_conditions(conditions):
        model_id = condition.get("model_id")
        if not model_id:
            raise TriggerValidationError(
                "An LLM condition needs a model_id: the chat or decision model instance "
                "that evaluates it"
            )
        try:
            model_uuid = UUID(str(model_id))
        except ValueError as error:
            raise TriggerValidationError(
                f"Condition model_id '{model_id}' is not a model instance id"
            ) from error
        instance = await instances.get_by_id(model_uuid)
        if instance is None:
            raise TriggerValidationError(
                f"Model instance '{model_id}' does not exist in this workspace"
            )
        kind = instance.model_spec.kind
        if kind not in CONDITION_MODEL_KINDS:
            raise TriggerValidationError(
                f"Model instance '{model_id}' is a {kind} model; a condition needs a chat "
                "or decision model"
            )
