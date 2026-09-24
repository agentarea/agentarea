"""An installed customer_pricing extension that cannot resolve must stop startup.

Falling back to the USD default instead would let one pod record provider USD
into the same task totals and budgets that its siblings record billing
currency into. Exiting hands the problem to the orchestrator, loudly.
"""

import agentarea_common.extensions as extensions_module
import pytest
from agentarea_common.extensions.customer_pricing import (
    CUSTOMER_PRICING_EXTENSION,
    CustomerPricingUnavailableError,
    get_customer_pricing,
)
from agentarea_common.extensions.registry import ExtensionRegistry


def _explode():
    raise RuntimeError("billing unreachable")


@pytest.fixture(autouse=True)
def broken_extension(monkeypatch):
    ExtensionRegistry.clear()
    get_customer_pricing.cache_clear()
    monkeypatch.setattr(
        extensions_module,
        "discover_extensions",
        lambda: ExtensionRegistry.register(CUSTOMER_PRICING_EXTENSION, _explode),
    )
    yield
    ExtensionRegistry.clear()
    get_customer_pricing.cache_clear()


@pytest.mark.asyncio
async def test_api_startup_fails():
    from agentarea_api.main import initialize_services

    with pytest.raises(CustomerPricingUnavailableError):
        await initialize_services()
