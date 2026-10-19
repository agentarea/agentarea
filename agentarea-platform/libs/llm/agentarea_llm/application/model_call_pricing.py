"""How a non-chat model call is funded before it runs: what it can cost at most.

Each estimate is in USD from the model's declared prices, or None when the model
declares none to estimate by; billing refuses to hold a call on the platform's
credentials against None (``model_unpriced``).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from agentarea_common.model_charges import ModelFunding, estimate_vendor_cost, hold_model_call

from agentarea_llm.infrastructure.model_clients import ModelTarget


def image_estimate(target: ModelTarget) -> Decimal | None:
    return target.output_cost_per_image


def video_estimate(target: ModelTarget, duration: int | None) -> Decimal | None:
    if target.output_cost_per_video_per_second is None or duration is None:
        return None
    return target.output_cost_per_video_per_second * Decimal(duration)


def decision_estimate(target: ModelTarget, request: Any) -> Decimal | None:
    if target.input_cost_per_token is None or target.output_cost_per_token is None:
        return None
    return estimate_vendor_cost(
        [request],
        target.max_output_tokens,
        target.input_cost_per_token,
        target.output_cost_per_token,
    )


def chat_estimate(target: ModelTarget, messages: list[Any], max_tokens: int) -> Decimal | None:
    if target.input_cost_per_token is None or target.output_cost_per_token is None:
        return None
    return estimate_vendor_cost(
        messages, max_tokens, target.input_cost_per_token, target.output_cost_per_token
    )


async def fund_model_call(
    target: ModelTarget,
    *,
    workspace_id: str,
    estimate: Decimal | None,
    idempotency_key: str,
) -> ModelFunding:
    """The funding a call on ``target`` is connected with (see ``ModelService.connect``)."""
    return await hold_model_call(
        workspace_id=workspace_id,
        model_instance_id=target.instance_id,
        managed_by=target.managed_by,
        vendor_cost_estimate=estimate,
        idempotency_key=idempotency_key,
    )
