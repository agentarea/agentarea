"""A per-token price reaches the bill exactly, through the workflow's cached model info."""

from decimal import Decimal

from agentarea_agents_sdk.models.llm_model import LLMModel, LLMUsage
from agentarea_execution.models import ChangeModelPayload, ResolvedModelInfo


def _info(model_cls, **prices):
    return model_cls(
        model_id="m-1",
        provider_type="openai",
        model_name="nano-priced",
        context_window=8192,
        **prices,
    )


def test_resolved_model_info_keeps_a_nano_dollar_price_across_the_temporal_payload():
    info = _info(
        ResolvedModelInfo,
        input_cost_per_token=Decimal("0.000000001"),
        output_cost_per_token=Decimal("0.000000123456"),
    )

    restored = ResolvedModelInfo.model_validate_json(info.model_dump_json())

    assert restored.input_cost_per_token == Decimal("0.000000001")
    assert restored.output_cost_per_token == Decimal("0.000000123456")


def test_change_model_payload_keeps_the_price_exact():
    payload = _info(ChangeModelPayload, input_cost_per_token="0.000000001")

    assert payload.input_cost_per_token == Decimal("0.000000001")


def test_a_million_tokens_at_a_nano_dollar_cost_exactly_a_tenth_of_a_cent():
    info = ResolvedModelInfo.model_validate_json(
        _info(
            ResolvedModelInfo,
            input_cost_per_token=Decimal("0.000000001"),
            output_cost_per_token=Decimal("0.000000002"),
        ).model_dump_json()
    )
    model = LLMModel(
        provider_type="openai",
        model_name="nano-priced",
        input_cost_per_token=info.input_cost_per_token,
        output_cost_per_token=info.output_cost_per_token,
    )

    cost = model._configured_cost(
        LLMUsage(prompt_tokens=1_000_000, completion_tokens=1_000_000, total_tokens=2_000_000)
    )

    assert isinstance(cost, Decimal)
    assert cost == Decimal("0.003")
