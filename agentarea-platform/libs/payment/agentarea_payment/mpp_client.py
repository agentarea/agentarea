"""MPP (Machine Payments Protocol) client."""

from __future__ import annotations

import logging
from typing import Any

from .models import PaymentResult

logger = logging.getLogger(__name__)


class MPPPaymentClient:
    """Wraps the pympp SDK for agent payment flows.

    Handles the MPP payment cycle:
    1. Receive 402 response with MPP challenge
    2. Create credential using Tempo account
    3. Retry request with Authorization header
    """

    def __init__(
        self,
        tempo_key: str,
        session_budget_usd: float = 10.0,
        payment_method_types: list[str] | None = None,
    ):
        self._tempo_key = tempo_key
        self._session_budget_usd = session_budget_usd
        self._payment_method_types = payment_method_types or ["charge"]
        self._client = None

    async def _get_client(self):
        """Lazily initialize the MPP client."""
        if self._client is not None:
            return self._client

        try:
            from mpp.client import Client
            from mpp.methods.tempo import TempoAccount, tempo, ChargeIntent

            account = TempoAccount.from_key(self._tempo_key)
            client = Client(
                methods=[tempo(account=account, intents={"charge": ChargeIntent()})]
            )
            self._client = client
            return client
        except ImportError:
            logger.warning("pympp SDK not installed. Install with: pip install pympp")
            raise

    async def handle_402(
        self,
        url: str,
        method: str,
        headers: dict[str, str],
        body: Any | None,
        response_headers: dict[str, str],
        response_body: str | bytes,
        budget_remaining: float,
    ) -> PaymentResult:
        """Handle a 402 response by making an MPP payment."""
        import json

        try:
            # Parse MPP challenge from response
            challenge_data = json.loads(response_body) if isinstance(response_body, (str, bytes)) else response_body

            amount = float(challenge_data.get("amount", 0))
            recipient = challenge_data.get("recipient", challenge_data.get("payTo", ""))

            if amount > budget_remaining:
                return PaymentResult(
                    success=False,
                    protocol="mpp",
                    amount_usd=amount,
                    recipient=recipient,
                    error=f"Payment ${amount:.4f} exceeds remaining budget ${budget_remaining:.2f}",
                )

            if amount > self._session_budget_usd:
                return PaymentResult(
                    success=False,
                    protocol="mpp",
                    amount_usd=amount,
                    recipient=recipient,
                    error=f"Payment ${amount:.4f} exceeds session budget ${self._session_budget_usd:.2f}",
                )

            # Use MPP client to handle payment — pympp handles the 402 flow automatically
            client = await self._get_client()
            response = await client.request(
                method=method,
                url=url,
                headers=headers,
            )

            tx_hash = None
            receipt = response.headers.get("X-MPP-Receipt") or response.headers.get("x-mpp-receipt")
            if receipt:
                try:
                    receipt_data = json.loads(receipt)
                    tx_hash = receipt_data.get("txHash") or receipt_data.get("transactionHash")
                except Exception:
                    pass

            if response.status_code == 200:
                return PaymentResult(
                    success=True,
                    protocol="mpp",
                    amount_usd=amount,
                    recipient=recipient,
                    tx_hash=tx_hash,
                    response_body=response.text,
                    response_status=response.status_code,
                    protocol_metadata={"payment_method": "charge"},
                )
            else:
                return PaymentResult(
                    success=False,
                    protocol="mpp",
                    amount_usd=amount,
                    recipient=recipient,
                    error=f"MPP retry failed with status {response.status_code}",
                    response_status=response.status_code,
                )

        except ImportError as e:
            return PaymentResult(
                success=False,
                protocol="mpp",
                amount_usd=0,
                recipient="",
                error=f"pympp SDK not available: {e}",
            )
        except Exception as e:
            logger.exception("MPP payment failed")
            return PaymentResult(
                success=False,
                protocol="mpp",
                amount_usd=0,
                recipient="",
                error=f"MPP payment error: {e}",
            )
