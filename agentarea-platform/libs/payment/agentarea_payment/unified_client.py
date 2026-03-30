"""Unified payment client that auto-detects protocol and delegates."""

from __future__ import annotations

import logging
from typing import Any

from .detector import PaymentProtocolDetector
from .models import PaymentResult

logger = logging.getLogger(__name__)


class UnifiedPaymentClient:
    """Facade that auto-detects x402 vs MPP from 402 responses and delegates payment."""

    def __init__(
        self,
        wallet_type: str,
        x402_config: dict[str, Any] | None = None,
        mpp_config: dict[str, Any] | None = None,
        x402_private_key: str | None = None,
        mpp_tempo_key: str | None = None,
    ):
        self._wallet_type = wallet_type
        self._x402_config = x402_config or {}
        self._mpp_config = mpp_config or {}
        self._x402_client = None
        self._mpp_client = None

        # Initialize x402 client if configured
        if wallet_type in ("x402", "dual") and x402_private_key:
            from .x402_client import X402PaymentClient

            self._x402_client = X402PaymentClient(
                private_key=x402_private_key,
                network=self._x402_config.get("network", "eip155:8453"),
                facilitator_url=self._x402_config.get(
                    "facilitator_url", "https://x402.org/facilitator"
                ),
                signer_type=self._x402_config.get("signer_type", "evm"),
            )

        # Initialize MPP client if configured
        if wallet_type in ("mpp", "dual") and mpp_tempo_key:
            from .mpp_client import MPPPaymentClient

            self._mpp_client = MPPPaymentClient(
                tempo_key=mpp_tempo_key,
                session_budget_usd=self._mpp_config.get("session_budget_usd", 10.0),
                payment_method_types=self._mpp_config.get("payment_method_types"),
            )

    async def handle_402(
        self,
        url: str,
        method: str,
        request_headers: dict[str, str],
        request_body: Any | None,
        response_status: int,
        response_headers: dict[str, str],
        response_body: str | bytes,
        budget_remaining: float,
    ) -> PaymentResult:
        """Handle a 402 response by detecting protocol and delegating to the right client."""
        protocol = PaymentProtocolDetector.detect(response_status, response_headers)

        if protocol is None:
            return PaymentResult(
                success=False,
                protocol="unknown",
                amount_usd=0,
                recipient="",
                error="Unknown 402 protocol - no recognized payment headers",
            )

        if protocol == "x402":
            if self._x402_client is None:
                return PaymentResult(
                    success=False,
                    protocol="x402",
                    amount_usd=0,
                    recipient="",
                    error="Wallet does not support x402 protocol",
                )
            return await self._x402_client.handle_402(
                url=url,
                method=method,
                headers=request_headers,
                body=request_body,
                response_headers=response_headers,
                budget_remaining=budget_remaining,
            )

        if protocol == "mpp":
            if self._mpp_client is None:
                return PaymentResult(
                    success=False,
                    protocol="mpp",
                    amount_usd=0,
                    recipient="",
                    error="Wallet does not support MPP protocol",
                )
            return await self._mpp_client.handle_402(
                url=url,
                method=method,
                headers=request_headers,
                body=request_body,
                response_headers=response_headers,
                response_body=response_body,
                budget_remaining=budget_remaining,
            )

        return PaymentResult(
            success=False,
            protocol=protocol,
            amount_usd=0,
            recipient="",
            error=f"Unsupported protocol: {protocol}",
        )
