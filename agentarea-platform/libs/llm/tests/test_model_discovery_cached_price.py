"""Discovery keeps the cached-input price a provider lists next to its token prices."""

from decimal import Decimal

from agentarea_llm.application.model_discovery_service import ModelDiscoveryService


def _discover(pricing: dict) -> list:
    return ModelDiscoveryService()._parse_response(
        "openrouter",
        {"data": [{"id": "vendor/model", "context_length": 32_000, "pricing": pricing}]},
    )


def test_a_listed_cache_read_price_is_the_cached_input_price():
    [model] = _discover(
        {"prompt": "0.000003", "completion": "0.000015", "input_cache_read": "0.0000003"}
    )

    assert model.cached_input_cost_per_token == Decimal("0.0000003")


def test_no_listed_cache_read_price_leaves_cached_tokens_at_the_input_price():
    [model] = _discover({"prompt": "0.000003", "completion": "0.000015"})

    assert model.cached_input_cost_per_token is None
