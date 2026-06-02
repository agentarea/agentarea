"""x402 payment protocol client."""

from __future__ import annotations

import json
import logging
from importlib import import_module
from typing import Any

from .models import PaymentResult

logger = logging.getLogger(__name__)


class X402PaymentClient:
    """Wraps the x402 Python SDK for agent payment flows.

    Handles the x402 payment cycle:
    1. Receive 402 response with PAYMENT-REQUIRED header
    2. Parse payment requirements
    3. Create payment payload (sign with agent's wallet)
    4. Retry request with PAYMENT-SIGNATURE header
    """

    def __init__(
        self,
        private_key: str,
        network: str = "eip155:8453",
        facilitator_url: str = "https://x402.org/facilitator",
        signer_type: str = "evm",
    ):
        self._private_key = private_key
        self._network = network
        self._facilitator_url = facilitator_url
        self._signer_type = signer_type
        self._client = None  # Lazy init

    def _get_client(self):
        """Lazily initialize the x402 client."""
        if self._client is not None:
            return self._client

        try:
            x402_client_cls = import_module("x402").x402Client
            exact_evm_scheme_cls = import_module("x402.mechanisms.evm.exact").ExactEvmScheme

            client = x402_client_cls()
            # Create signer from private key
            signer = self._create_signer()
            client.register("eip155:*", exact_evm_scheme_cls(signer=signer))
            self._client = client
            return client
        except ImportError:
            logger.warning("x402 SDK not installed. Install with: pip install x402[httpx,evm]")
            raise

    def _create_signer(self):
        """Create a signer from the private key."""
        try:
            account_cls = import_module("eth_account").Account

            return account_cls.from_key(self._private_key)
        except ImportError:
            # Fallback: x402 SDK may provide its own signer
            logger.warning("eth_account not available, attempting x402 native signer")
            raise

    async def handle_402(
        self,
        url: str,
        method: str,
        headers: dict[str, str],
        body: Any | None,
        response_headers: dict[str, str],
        budget_remaining: float,
    ) -> PaymentResult:
        """Handle a 402 response by making an x402 payment.

        Args:
            url: The original request URL
            method: HTTP method (GET, POST, etc.)
            headers: Original request headers
            body: Original request body
            response_headers: 402 response headers containing payment requirements
            budget_remaining: Maximum USD amount the agent can spend

        Returns:
            PaymentResult with payment outcome
        """
        import base64

        try:
            # Parse payment requirements from PAYMENT-REQUIRED header
            payment_required_raw = response_headers.get(
                "PAYMENT-REQUIRED", response_headers.get("payment-required", "")
            )
            if not payment_required_raw:
                return PaymentResult(
                    success=False,
                    protocol="x402",
                    amount_usd=0,
                    recipient="",
                    error="No PAYMENT-REQUIRED header found",
                )

            # Decode payment requirements
            try:
                payment_required = json.loads(base64.b64decode(payment_required_raw))
            except Exception:
                # Try as raw JSON
                payment_required = (
                    json.loads(payment_required_raw)
                    if isinstance(payment_required_raw, str)
                    else payment_required_raw
                )

            # Extract amount and check against budget
            amount = (
                float(payment_required.get("maxAmountRequired", 0)) / 1_000_000
            )  # USDC has 6 decimals
            recipient = payment_required.get("payTo", "")

            if amount > budget_remaining:
                return PaymentResult(
                    success=False,
                    protocol="x402",
                    amount_usd=amount,
                    recipient=recipient,
                    error=f"Payment ${amount:.4f} exceeds remaining budget ${budget_remaining:.2f}",
                )

            # Create payment payload using x402 client
            client = self._get_client()
            payload = await client.create_payment_payload(payment_required)

            # Retry request with payment
            import httpx

            payment_headers = {
                **headers,
                "PAYMENT-SIGNATURE": base64.b64encode(
                    json.dumps(payload).encode()
                    if isinstance(payload, dict)
                    else str(payload).encode()
                ).decode(),
            }

            async with httpx.AsyncClient() as http_client:
                response = await http_client.request(
                    method=method,
                    url=url,
                    headers=payment_headers,
                    content=json.dumps(body) if body else None,
                )

            if response.status_code == 200:
                # Extract tx hash from response headers if available
                payment_response = response.headers.get("PAYMENT-RESPONSE", "")
                tx_hash = None
                if payment_response:
                    try:
                        pr_data = json.loads(base64.b64decode(payment_response))
                        tx_hash = pr_data.get("txHash") or pr_data.get("transaction_hash")
                    except Exception:
                        logger.debug("Failed to parse x402 PAYMENT-RESPONSE header")

                return PaymentResult(
                    success=True,
                    protocol="x402",
                    amount_usd=amount,
                    recipient=recipient,
                    tx_hash=tx_hash,
                    response_body=response.text,
                    response_status=response.status_code,
                    protocol_metadata={"network": self._network, "scheme": "exact"},
                )
            else:
                return PaymentResult(
                    success=False,
                    protocol="x402",
                    amount_usd=amount,
                    recipient=recipient,
                    error=f"Payment retry failed with status {response.status_code}: {response.text[:200]}",
                    response_status=response.status_code,
                )

        except ImportError as e:
            return PaymentResult(
                success=False,
                protocol="x402",
                amount_usd=0,
                recipient="",
                error=f"x402 SDK not available: {e}",
            )
        except Exception as e:
            logger.exception("x402 payment failed")
            return PaymentResult(
                success=False,
                protocol="x402",
                amount_usd=0,
                recipient="",
                error=f"x402 payment error: {e}",
            )
