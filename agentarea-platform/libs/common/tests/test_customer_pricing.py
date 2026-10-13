"""Resolution of the customer_pricing extension and its OSS default."""

from decimal import Decimal

import pytest
from agentarea_common.extensions.customer_pricing import (
    CUSTOMER_PRICING_EXTENSION,
    CustomerPricing,
    CustomerPricingUnavailableError,
    FxUnavailableError,
    ProviderCostPricing,
    get_customer_pricing,
    price_compute_hour,
    price_llm_call,
    price_vendor_cost,
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

    async def price_vendor_cost(self, *, payer, connector, tool, vendor_cost, currency):
        factor = Decimal("1.5") if payer == "platform" else Decimal(1)
        return vendor_cost * factor * (Decimal(95) if currency == "USD" else Decimal(1))


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


class _EntryPoint:
    """Stands in for an installed distribution's entry point."""

    def __init__(self, name, load):
        self.name = name
        self.value = f"fake:{name}"
        self._load = load

    def load(self):
        return self._load()


def _broken_import():
    raise ImportError("No module named 'agentarea_enterprise.pricing'")


def _install(monkeypatch, *entry_points):
    from agentarea_common.extensions import discovery

    monkeypatch.setattr(discovery, "entry_points", lambda group: list(entry_points))


def test_installed_extension_that_fails_to_import_does_not_fall_back_to_usd(monkeypatch):
    """Discovery swallows the import error; resolution must not read it as "not installed"."""
    from agentarea_common.extensions import discover_extensions

    _install(monkeypatch, _EntryPoint(CUSTOMER_PRICING_EXTENSION, _broken_import))
    discover_extensions()

    with pytest.raises(CustomerPricingUnavailableError, match="failed to load: ImportError"):
        resolve_customer_pricing()


def test_other_extensions_failing_to_import_leave_pricing_alone(monkeypatch):
    from agentarea_common.extensions import discover_extensions

    _install(monkeypatch, _EntryPoint("audit_sink", _broken_import))
    discover_extensions()

    assert isinstance(resolve_customer_pricing(), ProviderCostPricing)


def test_a_working_copy_of_the_extension_supersedes_a_broken_one(monkeypatch):
    from agentarea_common.extensions import discover_extensions

    _install(
        monkeypatch,
        _EntryPoint(CUSTOMER_PRICING_EXTENSION, _broken_import),
        _EntryPoint(CUSTOMER_PRICING_EXTENSION, lambda: _Rub),
    )
    discover_extensions()

    assert resolve_customer_pricing().currency() == "RUB"


@pytest.mark.asyncio
async def test_without_billing_a_tool_cost_stays_in_the_vendors_currency():
    """OSS converts nothing: a RUB-priced tool's line is RUB, a USD one's USD."""
    for currency in ("USD", "RUB"):
        amount, line_currency = await price_vendor_cost(
            payer="platform",
            connector="c",
            tool="t",
            vendor_cost=Decimal("0.488"),
            currency=currency,
            pricing=ProviderCostPricing(),
        )

        assert (amount, line_currency) == (Decimal("0.488"), currency)


@pytest.mark.asyncio
async def test_a_tool_cost_is_priced_by_the_active_pricing():
    ExtensionRegistry.register(CUSTOMER_PRICING_EXTENSION, _Rub)

    amount = await price_vendor_cost(
        payer="platform", connector="c", tool="t", vendor_cost=Decimal("0.488"), currency="RUB"
    )

    assert amount == (Decimal("0.7320"), "RUB")


@pytest.mark.asyncio
async def test_a_currency_an_installed_pricing_cannot_convert_is_its_error():
    class _NoEur(_Rub):
        async def price_vendor_cost(self, *, payer, connector, tool, vendor_cost, currency):
            raise LookupError(f"no rate for {currency}")

    with pytest.raises(FxUnavailableError, match="EUR"):
        await price_vendor_cost(
            payer="workspace",
            connector="c",
            tool="t",
            vendor_cost=Decimal(1),
            currency="EUR",
            pricing=_NoEur(),
        )


@pytest.mark.asyncio
async def test_compute_is_unpriced_without_a_pricing_that_prices_it():
    assert await price_compute_hour(vcpu=Decimal(1), memory_gib=Decimal(1)) is None
    assert await price_compute_hour(vcpu=Decimal(1), memory_gib=Decimal(1), pricing=_Rub()) is None


@pytest.mark.asyncio
async def test_compute_is_priced_in_the_billing_currency():
    class _Compute(_Rub):
        async def price_compute_hour(self, *, vcpu, memory_gib):
            return vcpu + memory_gib * Decimal("0.12")

    assert await price_compute_hour(
        vcpu=Decimal("0.5"), memory_gib=Decimal(1), pricing=_Compute()
    ) == (Decimal("0.62"), "RUB")


@pytest.mark.asyncio
async def test_compute_billing_does_not_price_is_unpriced_not_an_error():
    class _Unpriced(_Rub):
        async def price_compute_hour(self, *, vcpu, memory_gib):
            raise LookupError("no compute cards")

    assert (
        await price_compute_hour(vcpu=Decimal(1), memory_gib=Decimal(1), pricing=_Unpriced())
        is None
    )
