"""Spend a cap does not count is reported, not converted and not blocked."""

from decimal import Decimal

from agentarea_tasks.spend_gate import spend_not_covered, workspace_cap_currencies


def test_only_currencies_no_cap_counts_are_reported():
    spend = {"USD": Decimal("3"), "RUB": Decimal("500"), "EUR": Decimal("0"), None: Decimal("1")}

    assert spend_not_covered(spend, {"USD"}) == {"RUB": Decimal("500")}
    assert spend_not_covered(spend, {"USD", "RUB"}) == {}


def test_a_workspace_cap_covers_its_own_currency_or_the_billing_currency():
    caps = [
        {"amount_usd": "100"},
        {"amount_usd": "9000", "currency": "RUB"},
        {"amount_usd": "5", "connection_id": "c1", "currency": "EUR"},
        {"amount_usd": "50", "period": "run", "currency": "GBP"},
    ]

    assert workspace_cap_currencies(caps, "USD") == {"USD", "RUB"}


def test_with_only_a_rub_cap_usd_spend_is_not_covered():
    spend = {"USD": Decimal("3"), "RUB": Decimal("500")}

    covered = workspace_cap_currencies([{"amount_usd": "900", "currency": "RUB"}], "USD")

    assert spend_not_covered(spend, covered) == {"USD": Decimal("3")}


def test_without_a_workspace_cap_nothing_is_reported():
    spend = {"USD": Decimal("3"), "RUB": Decimal("500")}

    assert spend_not_covered(spend, workspace_cap_currencies([], "USD")) == {}
