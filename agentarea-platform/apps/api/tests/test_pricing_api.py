"""GET /v1/pricing/currency names the currency every money amount is in."""

import pytest
from agentarea_api.api.v1.pricing import get_pricing_currency
from agentarea_common.auth.dependencies import get_user_context
from agentarea_common.extensions.customer_pricing import (
    CUSTOMER_PRICING_EXTENSION,
    get_customer_pricing,
)
from agentarea_common.extensions.registry import ExtensionRegistry
from fastapi.routing import APIRoute


@pytest.fixture(autouse=True)
def clean():
    ExtensionRegistry.clear()
    get_customer_pricing.cache_clear()
    yield
    ExtensionRegistry.clear()
    get_customer_pricing.cache_clear()


class _Rub:
    def currency(self) -> str:
        return "RUB"

    async def price_llm_call(self, **_kwargs):
        raise AssertionError("the currency endpoint must not price anything")


@pytest.mark.asyncio
async def test_oss_currency_is_usd():
    assert (await get_pricing_currency()).model_dump() == {"currency": "USD"}


@pytest.mark.asyncio
async def test_currency_comes_from_the_extension():
    ExtensionRegistry.register(CUSTOMER_PRICING_EXTENSION, _Rub)

    assert (await get_pricing_currency()).model_dump() == {"currency": "RUB"}


def test_route_is_served_behind_authentication():
    from agentarea_api.main import app

    route = next(
        r for r in app.routes if isinstance(r, APIRoute) and r.path == "/v1/pricing/currency"
    )
    stack, calls = list(route.dependant.dependencies), set()
    while stack:
        dep = stack.pop()
        calls.add(dep.call)
        stack.extend(dep.dependencies)

    assert route.methods == {"GET"}
    assert get_user_context in calls


def test_model_test_cost_is_labelled_usd():
    """The model test returns the provider's raw charge, not a billing-currency amount."""
    from agentarea_api.api.v1.model_instances import ModelInstanceTestResponse

    response = ModelInstanceTestResponse(success=True, message="ok", cost=0.0001)

    assert response.model_dump()["currency"] == "USD"
