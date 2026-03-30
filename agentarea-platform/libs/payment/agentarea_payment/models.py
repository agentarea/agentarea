"""Payment protocol data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PaymentResult:
    """Result of a payment attempt."""

    success: bool
    protocol: str  # "x402" or "mpp"
    amount_usd: float
    recipient: str
    tx_hash: str | None = None
    error: str | None = None
    response_body: Any = None
    response_status: int | None = None
    protocol_metadata: dict[str, Any] = field(default_factory=dict)
