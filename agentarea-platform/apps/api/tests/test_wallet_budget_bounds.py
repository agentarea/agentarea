"""A service budget must fit the NUMERIC(18, 6) column it is stored in."""

import pytest
from agentarea_api.api.v1.wallet import (
    CreateWalletRequest,
    FundWalletRequest,
    UpdateWalletRequest,
)
from pydantic import ValidationError

TOO_LARGE = "1000000000000"


def test_create_refuses_a_budget_the_column_cannot_hold():
    with pytest.raises(ValidationError):
        CreateWalletRequest(wallet_type="x402", service_budget_usd=TOO_LARGE)


def test_update_refuses_a_budget_the_column_cannot_hold():
    with pytest.raises(ValidationError):
        UpdateWalletRequest(service_budget_usd=TOO_LARGE)


def test_fund_refuses_a_budget_the_column_cannot_hold():
    with pytest.raises(ValidationError):
        FundWalletRequest(service_budget_usd=TOO_LARGE)


def test_the_largest_budget_the_column_holds_is_accepted():
    request = FundWalletRequest(service_budget_usd="999999999999.999999")

    assert str(request.service_budget_usd) == "999999999999.999999"


@pytest.mark.parametrize("model", [FundWalletRequest, UpdateWalletRequest])
def test_a_budget_that_rounds_up_to_the_ceiling_is_refused(model):
    """Postgres rounds to 6 places on insert; this one became 10**12 and overflowed."""
    with pytest.raises(ValidationError, match="less than"):
        model(service_budget_usd="999999999999.9999995")


def test_a_budget_is_rounded_as_the_column_rounds_it():
    request = CreateWalletRequest(wallet_type="x402", service_budget_usd="12.3456785")

    assert str(request.service_budget_usd) == "12.345679"


@pytest.mark.parametrize(
    "field, value",
    [("wallet_type", "bogus"), ("status", "bogus"), ("service_budget_period", "hourly")],
)
def test_an_update_refuses_values_the_wallet_does_not_know(field, value):
    """An unknown period summed spend over all time; an unknown status hid the wallet."""
    with pytest.raises(ValidationError):
        UpdateWalletRequest.model_validate({field: value})


def test_a_create_refuses_an_unknown_wallet_type_or_period():
    with pytest.raises(ValidationError):
        CreateWalletRequest.model_validate({"wallet_type": "bogus"})
    with pytest.raises(ValidationError):
        CreateWalletRequest.model_validate(
            {"wallet_type": "x402", "service_budget_period": "hourly"}
        )


def test_the_known_values_are_accepted():
    request = UpdateWalletRequest.model_validate(
        {"wallet_type": "dual", "status": "disabled", "service_budget_period": "monthly"}
    )

    assert (request.wallet_type, request.status, request.service_budget_period) == (
        "dual",
        "disabled",
        "monthly",
    )
