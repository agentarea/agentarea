"""Tests for wallet domain models, validation, and service logic."""

import pytest
from agentarea_wallet.domain.enums import (
    BudgetPeriod,
    PaymentProtocol,
    PaymentStatus,
    WalletStatus,
    WalletType,
)
from agentarea_wallet.domain.exceptions import (
    InsufficientBudgetError,
    UnsupportedProtocolError,
    WalletAlreadyExistsError,
    WalletNotFoundError,
)


class TestWalletEnums:
    def test_wallet_type_values(self):
        assert WalletType.X402 == "x402"
        assert WalletType.MPP == "mpp"
        assert WalletType.DUAL == "dual"

    def test_wallet_status_values(self):
        assert WalletStatus.ACTIVE == "active"
        assert WalletStatus.DISABLED == "disabled"

    def test_budget_period_values(self):
        assert BudgetPeriod.EXECUTION == "execution"
        assert BudgetPeriod.DAILY == "daily"
        assert BudgetPeriod.MONTHLY == "monthly"

    def test_payment_protocol_values(self):
        assert PaymentProtocol.X402 == "x402"
        assert PaymentProtocol.MPP == "mpp"

    def test_payment_status_values(self):
        assert PaymentStatus.COMPLETED == "completed"
        assert PaymentStatus.FAILED == "failed"
        assert PaymentStatus.PENDING == "pending"


class TestWalletExceptions:
    def test_wallet_already_exists_error(self):
        with pytest.raises(WalletAlreadyExistsError):
            raise WalletAlreadyExistsError("Wallet exists")

    def test_wallet_not_found_error(self):
        with pytest.raises(WalletNotFoundError):
            raise WalletNotFoundError("Not found")

    def test_insufficient_budget_error(self):
        with pytest.raises(InsufficientBudgetError):
            raise InsufficientBudgetError("Budget exceeded")

    def test_unsupported_protocol_error(self):
        with pytest.raises(UnsupportedProtocolError):
            raise UnsupportedProtocolError("Unsupported")


class TestWalletValidation:
    """Test the validation logic that would be in WalletService._validate_config."""

    def test_x402_requires_x402_config(self):
        """x402 wallet type requires x402_config."""
        from agentarea_wallet.application.wallet_service import WalletService

        with pytest.raises(ValueError, match="x402_config"):
            WalletService._validate_config("x402", x402_config=None, mpp_config=None)

    def test_mpp_requires_mpp_config(self):
        """mpp wallet type requires mpp_config."""
        from agentarea_wallet.application.wallet_service import WalletService

        with pytest.raises(ValueError, match="mpp_config"):
            WalletService._validate_config("mpp", x402_config=None, mpp_config=None)

    def test_dual_requires_both_configs(self):
        """dual wallet type requires both configs."""
        from agentarea_wallet.application.wallet_service import WalletService

        with pytest.raises(ValueError, match="x402_config"):
            WalletService._validate_config("dual", x402_config=None, mpp_config={"charge": True})

        with pytest.raises(ValueError, match="mpp_config"):
            WalletService._validate_config("dual", x402_config={"network": "base"}, mpp_config=None)

    def test_dual_with_both_configs_passes(self):
        """dual with both configs should not raise."""
        from agentarea_wallet.application.wallet_service import WalletService

        # Should not raise
        WalletService._validate_config(
            "dual",
            x402_config={"network": "eip155:8453"},
            mpp_config={"payment_method_types": ["charge"]},
        )

    def test_x402_with_config_passes(self):
        from agentarea_wallet.application.wallet_service import WalletService

        WalletService._validate_config(
            "x402",
            x402_config={"network": "eip155:8453"},
            mpp_config=None,
        )
