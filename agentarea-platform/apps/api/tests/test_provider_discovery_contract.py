"""A discovered model becomes a spec once it can run: it needs a context window.

An entry without one is kept out of the usable half of the batch and reported,
rather than failing the whole discovery. A price is optional.
"""

from agentarea_api.api.v1.provider_configs import _partition_discovered
from agentarea_llm.application.model_discovery_service import DiscoveredModel


def test_a_discovered_model_without_a_context_window_is_rejected_before_persistence():
    model = DiscoveredModel(
        model_name="unknown-limits",
        display_name="Unknown limits",
    )

    usable, skipped = _partition_discovered([model])

    assert usable == []
    assert [s.model_name for s in skipped] == ["unknown-limits"]
    assert skipped[0].missing == ["context_window"]


def test_a_discovered_model_without_a_price_is_accepted():
    model = DiscoveredModel(model_name="local", display_name="Local", context_window=8192)

    usable, skipped = _partition_discovered([model])

    assert [m.model_name for m in usable] == ["local"]
    assert skipped == []
