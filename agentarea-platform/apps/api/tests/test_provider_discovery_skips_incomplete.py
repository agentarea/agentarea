"""One incomplete catalog entry must not sink discovery for the whole provider.

A run needs a model's context window; its price is optional. A self-hosted
endpoint lists no prices, and a model without one is still added: its runs are
billed at what the provider reports, or not at all on the member's own key.
"""

import pytest
from agentarea_api.api.v1.provider_configs import (
    _missing_runtime_metadata,
    _partition_discovered,
    _require_any_usable_model,
)
from agentarea_llm.application.model_discovery_service import DiscoveredModel
from fastapi import HTTPException


def _model(name, *, context_window=8192, inp=1e-6, out=2e-6):
    return DiscoveredModel(
        model_name=name,
        display_name=name,
        context_window=context_window,
        input_cost_per_token=inp,
        output_cost_per_token=out,
    )


def test_complete_model_is_missing_nothing():
    assert _missing_runtime_metadata(_model("openai/gpt-5")) == []


def test_a_model_without_a_price_is_missing_nothing():
    assert _missing_runtime_metadata(_model("llama3.1:8b", inp=None, out=None)) == []


def test_missing_fields_are_named():
    model = _model("openrouter/auto-beta", inp=None, out=None, context_window=None)
    assert _missing_runtime_metadata(model) == ["context_window"]


def test_zero_and_bool_context_windows_are_rejected():
    assert "context_window" in _missing_runtime_metadata(_model("a", context_window=0))
    assert "context_window" in _missing_runtime_metadata(_model("b", context_window=True))


def test_one_model_without_a_context_window_does_not_sink_the_batch():
    batch = [
        _model("openai/gpt-5"),
        _model("openrouter/auto-beta", context_window=None),
        _model("qwen3:32b", inp=None, out=None),
    ]

    usable, skipped = _partition_discovered(batch)

    assert [m.model_name for m in usable] == ["openai/gpt-5", "qwen3:32b"]
    assert [s.model_name for s in skipped] == ["openrouter/auto-beta"]
    assert skipped[0].missing == ["context_window"]


def test_a_batch_with_nothing_runnable_still_fails_loudly():
    _, skipped = _partition_discovered(
        [_model("x", context_window=None), _model("y", context_window=None)]
    )

    with pytest.raises(HTTPException) as exc:
        _require_any_usable_model("openrouter", [], skipped)

    assert exc.value.status_code == 422
    assert "2 skipped" in exc.value.detail


def test_usable_models_pass_the_gate():
    _require_any_usable_model("openrouter", [_model("openai/gpt-5")], [])


def test_a_media_model_needs_no_token_prices_or_context_window():
    from agentarea_llm.domain.models import ModelKind

    for kind in (ModelKind.IMAGE, ModelKind.VIDEO, ModelKind.DECISION):
        model = _model("veo", inp=None, out=None, context_window=None)
        model.kind = kind
        assert _missing_runtime_metadata(model) == []


def test_a_model_no_surface_takes_is_skipped_as_kindless():
    model = _model("tts")
    model.kind = None
    assert _missing_runtime_metadata(model) == ["kind"]
