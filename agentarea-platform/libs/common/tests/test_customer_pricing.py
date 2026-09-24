"""Resolution of the customer_pricing extension and its OSS default."""

from decimal import Decimal

import pytest
from agentarea_common.extensions.customer_pricing import (
    CUSTOMER_PRICING_EXTENSION,
    CustomerPricing,
    CustomerPricingUnavailableError,
    ProviderCostPricing,
    get_customer_pricing,
    price_llm_call,
    resolve_customer_pricing,
)
from agentarea_common.extensions.registry import ExtensionRegistry


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

    async def price_llm_call(
        self,
        *,
        model_instance_id,
        platform_funded,
        prompt_tokens,
        completion_tokens,
        provider_cost_usd,
    ):
        return provider_cost_usd * 95


@pytest.mark.asyncio
async def test_default_is_provider_cost_in_usd():
    pricing = ProviderCostPricing()

    amount = await pricing.price_llm_call(
        model_instance_id="m",
        platform_funded=True,
        prompt_tokens=1000,
        completion_tokens=500,
        provider_cost_usd=Decimal("0.0123"),
    )

    assert pricing.currency() == "USD"
    assert amount == Decimal("0.0123")
    assert isinstance(pricing, CustomerPricing)


def test_no_extension_resolves_to_default():
    assert isinstance(resolve_customer_pricing(), ProviderCostPricing)


def test_registered_extension_is_used():
    ExtensionRegistry.register(CUSTOMER_PRICING_EXTENSION, _Rub)

    pricing = resolve_customer_pricing()

    assert isinstance(pricing, _Rub)
    assert pricing.currency() == "RUB"


def test_failing_installed_extension_does_not_fall_back_to_usd():
    """An installed extension that cannot load leaves the currency unknown."""

    def explode():
        raise RuntimeError("billing unreachable")

    ExtensionRegistry.register(CUSTOMER_PRICING_EXTENSION, explode)

    with pytest.raises(CustomerPricingUnavailableError, match="billing unreachable"):
        resolve_customer_pricing()


def test_non_conforming_extension_does_not_fall_back_to_usd():
    ExtensionRegistry.register(CUSTOMER_PRICING_EXTENSION, lambda: object())

    with pytest.raises(CustomerPricingUnavailableError, match="not a CustomerPricing"):
        resolve_customer_pricing()


def test_failed_resolution_is_not_cached():
    """A pod whose billing was down at first use recovers without a restart."""
    attempts = []

    def flaky():
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("billing unreachable")
        return _Rub()

    ExtensionRegistry.register(CUSTOMER_PRICING_EXTENSION, flaky)

    with pytest.raises(CustomerPricingUnavailableError):
        get_customer_pricing()
    assert get_customer_pricing().currency() == "RUB"


@pytest.mark.asyncio
async def test_lazy_resolution_failure_fails_the_call_as_accounting_error():
    """Never price in USD because the installed extension did not resolve."""
    ExtensionRegistry.register(CUSTOMER_PRICING_EXTENSION, lambda: object())

    with pytest.raises(RuntimeError, match="LLM usage accounting unavailable") as raised:
        await price_llm_call(
            model_instance_id="m",
            platform_funded=True,
            prompt_tokens=1,
            completion_tokens=1,
            provider_cost_usd=Decimal("0.01"),
        )

    assert isinstance(raised.value.__cause__, CustomerPricingUnavailableError)


def test_process_pricing_is_resolved_once_and_lazily():
    """Resolved on first use, so it sees extensions discovered after import."""
    calls = []

    def factory():
        calls.append(1)
        return _Rub()

    # Registered after import and after the module-level function exists: the
    # worker builds its services before discovery, and this is that ordering.
    ExtensionRegistry.register(CUSTOMER_PRICING_EXTENSION, factory)

    first = get_customer_pricing()
    second = get_customer_pricing()

    assert first is second
    assert first.currency() == "RUB"
    assert calls == [1]
