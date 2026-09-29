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
