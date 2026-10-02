"""Decisions for one agent, on the decision model its toolset settings name."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from agentarea_common.extensions.customer_pricing import CustomerPricing
from agentarea_common.money import Money

from agentarea_llm.application.model_call_pricing import price_model_call
from agentarea_llm.application.model_service import ModelService


class DecisionModelNotConfiguredError(ValueError):
    """agentarea/decide was called without a decision model in its settings."""


@dataclass(frozen=True)
class DecisionOutcome:
    answers: dict[str, dict[str, Any]]
    cost: Money
    currency: str


class DecisionService:
    def __init__(
        self,
        *,
        models: ModelService,
        model_id: str | None,
        pricing: CustomerPricing | None = None,
    ) -> None:
        self._models = models
        self._model_id = model_id
        # None = the process-wide pricing, resolved per call (see get_customer_pricing).
        self._pricing = pricing

    async def evaluate(self, state: str, questions: Mapping[str, Any]) -> DecisionOutcome:
        if not self._model_id:
            raise DecisionModelNotConfiguredError(
                "no decision model is configured for agentarea/decide"
            )
        model = await self._models.decision_model(self._model_id)
        result = await model.evaluate(state, questions)
        priced = await price_model_call(
            model.endpoint,
            provider_cost_usd=result.cost_usd,
            prompt_tokens=result.input_tokens,
            completion_tokens=result.output_tokens,
            pricing=self._pricing,
        )
        return DecisionOutcome(answers=result.answers, cost=priced.amount, currency=priced.currency)
