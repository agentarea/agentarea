"""One incomplete catalog entry must not sink discovery for the whole provider.

OpenRouter publishes router meta-models (``openrouter/auto-beta``) with no
pricing at all. Rejecting the batch on the first of them made discovery return
422 for the entire provider, so no model could be added.
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


def test_missing_fields_are_named():
    model = _model("openrouter/auto-beta", inp=None, out=None, context_window=None)
    assert _missing_runtime_metadata(model) == [
        "context_window",
        "input_cost_per_token",
        "output_cost_per_token",
    ]


def test_zero_and_bool_context_windows_are_rejected():
    assert "context_window" in _missing_runtime_metadata(_model("a", context_window=0))
    assert "context_window" in _missing_runtime_metadata(_model("b", context_window=True))


def test_one_priceless_model_does_not_sink_the_batch():
    batch = [
        _model("openai/gpt-5"),
        _model("openrouter/auto-beta", inp=None, out=None),
        _model("anthropic/claude-sonnet-5"),
    ]

    usable, skipped = _partition_discovered(batch)

    assert [m.model_name for m in usable] == ["openai/gpt-5", "anthropic/claude-sonnet-5"]
    assert [s.model_name for s in skipped] == ["openrouter/auto-beta"]
    assert skipped[0].missing == ["input_cost_per_token", "output_cost_per_token"]


def test_rejects_are_reported_not_dropped():
    """A shorter list with no explanation would read as a successful discovery."""
    _, skipped = _partition_discovered([_model("x", inp=None)])

    assert len(skipped) == 1
    assert skipped[0].missing == ["input_cost_per_token"]


def test_a_batch_with_nothing_runnable_still_fails_loudly():
    _, skipped = _partition_discovered([_model("x", inp=None), _model("y", out=None)])

    with pytest.raises(HTTPException) as exc:
        _require_any_usable_model("openrouter", [], skipped)

    assert exc.value.status_code == 422
    assert "2 skipped" in exc.value.detail


def test_usable_models_pass_the_gate():
    _require_any_usable_model("openrouter", [_model("openai/gpt-5")], [])
