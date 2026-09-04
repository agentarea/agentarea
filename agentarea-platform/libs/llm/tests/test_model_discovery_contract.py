"""Provider discovery must preserve unknown runtime metadata as unknown."""

from agentarea_llm.application.model_discovery_service import ModelDiscoveryService


def test_discovery_does_not_invent_context_or_output_limits():
    models = ModelDiscoveryService()._parse_response(
        "openai",
        {"data": [{"id": "vendor-model"}]},
    )

    assert len(models) == 1
    assert models[0].context_window is None
    assert models[0].max_output_tokens is None
    assert models[0].input_cost_per_token is None
    assert models[0].output_cost_per_token is None


def test_discovery_parses_explicit_runtime_metadata():
    models = ModelDiscoveryService()._parse_response(
        "openrouter",
        {
            "data": [
                {
                    "id": "priced-model",
                    "context_length": 128_000,
                    "top_provider": {"max_completion_tokens": 8192},
                    "pricing": {"prompt": "0.000001", "completion": "0.000002"},
                }
            ]
        },
    )

    model = models[0]
    assert model.context_window == 128_000
    assert model.max_output_tokens == 8192
    assert model.input_cost_per_token == 0.000001
    assert model.output_cost_per_token == 0.000002
