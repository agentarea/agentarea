"""Discovered models are not executable until runtime metadata is explicit."""

import pytest
from agentarea_api.api.v1.provider_configs import _require_discovered_runtime_metadata
from agentarea_llm.application.model_discovery_service import DiscoveredModel
from fastapi import HTTPException


def test_incomplete_discovered_model_is_rejected_before_persistence():
    model = DiscoveredModel(
        model_name="unknown-limits",
        display_name="Unknown limits",
    )

    with pytest.raises(HTTPException) as exc_info:
        _require_discovered_runtime_metadata(model)

    assert exc_info.value.status_code == 422
    assert "context_window" in str(exc_info.value.detail)
    assert "input_cost_per_token" in str(exc_info.value.detail)


def test_complete_discovered_model_is_accepted():
    _require_discovered_runtime_metadata(
        DiscoveredModel(
            model_name="configured",
            display_name="Configured",
            context_window=8192,
            input_cost_per_token=0,
            output_cost_per_token=0,
        )
    )
