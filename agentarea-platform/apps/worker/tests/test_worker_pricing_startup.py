"""An installed customer_pricing extension that cannot resolve must stop the worker.

The worker is where LLM calls are priced, so a worker that fell back to USD
would write provider USD into totals the rest of the deployment keeps in the
billing currency.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import agentarea_common.extensions as extensions_module
import pytest
from agentarea_common.extensions.customer_pricing import (
    CUSTOMER_PRICING_EXTENSION,
    CustomerPricingUnavailableError,
    get_customer_pricing,
)
from agentarea_common.extensions.registry import ExtensionRegistry
from agentarea_worker import main as worker_main


def _explode():
    raise RuntimeError("billing unreachable")


@pytest.fixture(autouse=True)
def clean():
    ExtensionRegistry.clear()
    get_customer_pricing.cache_clear()
    yield
    ExtensionRegistry.clear()
    get_customer_pricing.cache_clear()


async def test_worker_startup_fails(monkeypatch):
    monkeypatch.setattr(
        extensions_module,
        "discover_extensions",
        lambda: ExtensionRegistry.register(CUSTOMER_PRICING_EXTENSION, _explode),
    )
    # Everything create_worker does before discovery, stubbed: none of it is under test.
    monkeypatch.setattr(worker_main, "create_activity_dependencies", lambda: SimpleNamespace())
    monkeypatch.setattr(worker_main, "create_activities_for_worker", Mock(return_value=[]))
    monkeypatch.setattr(worker_main, "make_mcp_activities", Mock(return_value=[]))
    monkeypatch.setattr(worker_main, "initialize_di_container", Mock())
    worker = worker_main.AgentAreaWorker()
    worker.client = Mock()
    monkeypatch.setattr(worker, "_check_database", AsyncMock())

    with pytest.raises(CustomerPricingUnavailableError):
        await worker.create_worker()
