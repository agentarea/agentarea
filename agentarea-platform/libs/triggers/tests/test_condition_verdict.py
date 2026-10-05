from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from agentarea_triggers.domain.models import ConditionVerdict
from agentarea_triggers.llm_condition_evaluator import (
    LLMConditionEvaluationError,
    LLMConditionEvaluator,
)

CONDITION = {"type": "llm", "description": "a refund request", "model_id": str(uuid4())}


def _evaluator() -> LLMConditionEvaluator:
    instances = AsyncMock()
    instance = MagicMock()
    instance.model_spec.kind = "chat"
    instances.get.return_value = instance
    model_service = AsyncMock()
    model_service.resolve.return_value = MagicMock(
        provider_type="openai", model_name="gpt-4", api_key=None, endpoint_url=None
    )
    return LLMConditionEvaluator(
        model_instance_service=instances, secret_manager=AsyncMock(), model_service=model_service
    )


def _reply(content: str):
    response = MagicMock()
    response.choices = [MagicMock(message=MagicMock(content=content))]
    return patch(
        "agentarea_triggers.llm_condition_evaluator.litellm.acompletion",
        new=AsyncMock(return_value=response),
    )


async def test_the_verdict_carries_score_and_reason():
    with _reply('{"verdict": "met", "score": 0.82, "reason": "asks for money back"}'):
        verdict = await _evaluator().evaluate_structured(CONDITION, {"text": "refund pls"})
    assert verdict == ConditionVerdict(verdict="met", score=0.82, reason="asks for money back")
    assert verdict.met


async def test_a_fenced_json_reply_is_read():
    with _reply('```json\n{"verdict": "not_met", "score": 0.1, "reason": "a greeting"}\n```'):
        verdict = await _evaluator().evaluate_structured(CONDITION, {"text": "hi"})
    assert verdict.verdict == "not_met"


@pytest.mark.parametrize(
    "content",
    [
        "yes, the condition is met",
        '{"verdict": "probably", "reason": "?"}',
        '{"verdict": "met"}',
        '{"verdict": "met", "score": 7, "reason": "x"}',
    ],
)
async def test_anything_but_a_valid_verdict_fails_closed(content):
    with _reply(content), pytest.raises(LLMConditionEvaluationError):
        await _evaluator().evaluate_structured(CONDITION, {"text": "x"})


async def test_rules_report_which_way_they_went():
    condition = {"type": "rule", "rules": [{"field": "a", "operator": "eq", "value": 1}]}
    verdict = await _evaluator().evaluate_structured(condition, {"a": 2})
    assert verdict.verdict == "not_met"
    assert "rule" in verdict.reason


async def test_an_llm_condition_without_a_model_is_refused_not_defaulted():
    with pytest.raises(LLMConditionEvaluationError, match="model_id"):
        await _evaluator().evaluate_structured({"type": "llm", "description": "x"}, {})
