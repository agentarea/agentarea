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


# Money left the wallet. A paid request that settled and then failed is still spent.
SETTLED_PAYMENT_STATUSES: tuple[PaymentStatus, ...] = (PaymentStatus.COMPLETED,)


def settlement_status(*, request_succeeded: bool, tx_hash: str | None) -> PaymentStatus:
    """Status of a payment by whether it settled, not by whether the paid request succeeded.

    A successful paid request means the provider settled. A settlement receipt on a
    failed one means the same: the payment went through and the request failed after.
    """
    if request_succeeded or tx_hash:
        return PaymentStatus.COMPLETED
    return PaymentStatus.FAILED
