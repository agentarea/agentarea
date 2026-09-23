"""Discovered models are not executable until runtime metadata is explicit.

The guarantee is that an incomplete entry never becomes a model spec. It is
enforced by keeping such an entry out of the usable half of the batch (and
reporting it), rather than by failing the whole discovery.
"""

from agentarea_api.api.v1.provider_configs import _partition_discovered
from agentarea_llm.application.model_discovery_service import DiscoveredModel


def test_incomplete_discovered_model_is_rejected_before_persistence():
    model = DiscoveredModel(
        model_name="unknown-limits",
        display_name="Unknown limits",
    )

    usable, skipped = _partition_discovered([model])

    assert usable == []
    assert [s.model_name for s in skipped] == ["unknown-limits"]
    assert "context_window" in skipped[0].missing
    assert "input_cost_per_token" in skipped[0].missing


def test_complete_discovered_model_is_accepted():
    model = DiscoveredModel(
        model_name="configured",
        display_name="Configured",
        context_window=8192,
        input_cost_per_token=0,
        output_cost_per_token=0,
    )

    usable, skipped = _partition_discovered([model])

    assert [m.model_name for m in usable] == ["configured"]
    assert skipped == []
