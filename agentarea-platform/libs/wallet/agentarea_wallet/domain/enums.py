"""Enums for the wallet domain."""

from enum import StrEnum


class WalletType(StrEnum):
    """Supported wallet types."""

    X402 = "x402"
    MPP = "mpp"
    DUAL = "dual"


class WalletStatus(StrEnum):
    """Wallet operational status."""

    ACTIVE = "active"
    DISABLED = "disabled"


class BudgetPeriod(StrEnum):
    """Budget reset period."""

    EXECUTION = "execution"
    DAILY = "daily"
    MONTHLY = "monthly"


class PaymentProtocol(StrEnum):
    """Payment protocol used for a transaction."""

    X402 = "x402"
    MPP = "mpp"


class PaymentStatus(StrEnum):
    """Payment record status."""

    COMPLETED = "completed"
    FAILED = "failed"
    PENDING = "pending"
