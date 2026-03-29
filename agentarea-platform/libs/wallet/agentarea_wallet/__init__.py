"""AgentArea Wallet Library.

Provides wallet and payment management for agents supporting x402 and MPP protocols.
"""

__version__ = "0.0.8"

from agentarea_wallet.application.wallet_service import WalletService
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
from agentarea_wallet.domain.models import AgentWallet, PaymentRecord
from agentarea_wallet.infrastructure.repository import PaymentRecordRepository, WalletRepository

__all__ = [
    "AgentWallet",
    "BudgetPeriod",
    "InsufficientBudgetError",
    "PaymentProtocol",
    "PaymentRecord",
    "PaymentRecordRepository",
    "PaymentStatus",
    "UnsupportedProtocolError",
    "WalletAlreadyExistsError",
    "WalletNotFoundError",
    "WalletRepository",
    "WalletService",
    "WalletStatus",
    "WalletType",
]
