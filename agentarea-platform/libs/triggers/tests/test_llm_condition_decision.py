"""A decision-kind model answers a trigger condition as a yes/no question; chat keeps its path."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from agentarea_triggers.llm_condition_evaluator import (
    LLMConditionEvaluationError,
    LLMConditionEvaluator,
)

MODEL = uuid4()
CONDITION = {
    "type": "llm",
    "description": "the customer is asking for a refund",
    "model_id": str(MODEL),
}
EVENT = {"message": "I want my money back"}


def _instances(kind: str):
    service = AsyncMock()
    instance = MagicMock()
    instance.model_spec.kind = kind
    instance.model_spec.model_name = "gpt-4"
    instance.provider_config.provider_spec.provider_type = "openai"
    instance.provider_config.api_key = None
    instance.model_spec.endpoint_url = None
    service.get.return_value = instance
    return service


class _Decisions:
    def __init__(self, choice: str):
        self.choice = choice
        self.asked: list = []

    async def resolve(self, instance_id, kind):
        return SimpleNamespace(
            provider_type="openai",
            model_name="gpt-4",
            api_key="sk-resolved",  # pragma: allowlist secret
            endpoint_url=None,
        )

    async def decision_model(self, instance_id):
        async def evaluate(state, questions):
            self.asked.append((instance_id, state, questions))
            return SimpleNamespace(
                answers={"condition_met": {"type": "choice", "choice": self.choice}},
                cost_usd=0,
            )

        return SimpleNamespace(evaluate=evaluate)


def _evaluator(kind: str, decisions: _Decisions) -> LLMConditionEvaluator:
    return LLMConditionEvaluator(
        model_instance_service=_instances(kind),
        secret_manager=MagicMock(),
        model_service=decisions,
    )


@pytest.mark.parametrize("choice, expected", [("true", True), ("false", False)])
async def test_a_decision_model_answers_the_condition(choice, expected):
    decisions = _Decisions(choice)

    with patch("agentarea_triggers.llm_condition_evaluator.litellm.acompletion") as chat:
        met = await _evaluator("decision", decisions).evaluate_condition(CONDITION, EVENT)

    assert met is expected
    chat.assert_not_called()
    [(instance_id, state, questions)] = decisions.asked
    assert instance_id == MODEL
    assert state["event"] == EVENT
    assert questions == {
        "condition_met": {
            "type": "choice",
            "instructions": "Is this condition met by the event: the customer is asking for a refund",
            "criteria": {
                "true": "The event meets the condition",
                "false": "The event does not meet the condition",
            },
        }
    }


async def test_a_chat_model_keeps_the_completion_path():
    decisions = _Decisions("true")
    response = MagicMock()
    response.choices = [MagicMock(message=MagicMock(content="true"))]

    with patch(
        "agentarea_triggers.llm_condition_evaluator.litellm.acompletion",
        new=AsyncMock(return_value=response),
    ) as chat:
        met = await _evaluator("chat", decisions).evaluate_condition(CONDITION, EVENT)

    assert met is True
    chat.assert_awaited_once()
    assert chat.await_args.kwargs["api_key"] == "sk-resolved"  # pragma: allowlist secret
    assert chat.await_args.kwargs["model"] == "openai/gpt-4"
    assert decisions.asked == []


async def test_a_media_model_cannot_evaluate_a_condition():
    with pytest.raises(LLMConditionEvaluationError, match="image"):
        await _evaluator("image", _Decisions("true")).evaluate_condition(CONDITION, EVENT)


async def test_a_condition_without_its_own_model_is_refused():
    condition = {"type": "llm", "description": "the customer is asking for a refund"}

    with pytest.raises(LLMConditionEvaluationError, match="model_id"):
        await _evaluator("chat", _Decisions("true")).evaluate_condition(condition, EVENT)


async def test_each_sub_condition_uses_its_own_model():
    decisions = _Decisions("true")
    first, second = uuid4(), uuid4()
    combined = {
        "type": "combined",
        "logic": "AND",
        "conditions": [
            {**CONDITION, "model_id": str(first)},
            {**CONDITION, "model_id": str(second)},
        ],
    }

    assert await _evaluator("decision", decisions).evaluate_condition(combined, EVENT) is True
    assert [instance_id for instance_id, _, _ in decisions.asked] == [first, second]
