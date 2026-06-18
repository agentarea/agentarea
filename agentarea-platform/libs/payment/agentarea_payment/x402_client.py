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
            register_exact_evm_client = import_module(
                "x402.mechanisms.evm.exact.register"
            ).register_exact_evm_client

            client = x402_client_cls()
            signer = self._create_signer()
            register_exact_evm_client(client, signer, networks=self._network or None)
            self._client = client
            return client
        except ImportError:
            logger.warning("x402 SDK not installed. Install with: pip install x402[httpx,evm]")
            raise

    def _create_signer(self):
        """Create a signer from the private key."""
        try:
            account_cls = import_module("eth_account").Account
            signer_cls = import_module("x402.mechanisms.evm").EthAccountSigner

            return signer_cls(account_cls.from_key(self._private_key))
        except ImportError:
            logger.warning("eth_account or x402 EVM signer is not available")
            raise

    @staticmethod
    def _decode_payment_required(raw: str) -> dict[str, Any]:
        """Decode PAYMENT-REQUIRED as JSON or base64/base64url JSON."""
        import base64
        import binascii

        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            last_error: Exception = exc

        padded = raw + "=" * (-len(raw) % 4)
        for decoder in (base64.b64decode, base64.urlsafe_b64decode):
            try:
                decoded = decoder(padded.encode()).decode()
                return json.loads(decoded)
            except (binascii.Error, json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
                last_error = exc
        raise ValueError("Invalid PAYMENT-REQUIRED header") from last_error

    def _select_payment_requirement(self, payment_required: dict[str, Any]) -> dict[str, Any]:
        """Pick the requirement used for budget checks from an x402 challenge."""
        accepts = payment_required.get("accepts")
        if isinstance(accepts, list) and accepts:
            for requirement in accepts:
                if not isinstance(requirement, dict):
                    continue
                network = str(requirement.get("network") or "")
                if self._network and network and network != self._network:
                    continue
                return requirement
            first = accepts[0]
            return first if isinstance(first, dict) else payment_required
        return payment_required

    @staticmethod
    def _extract_amount_usd(requirement: dict[str, Any]) -> float:
        """Extract USD amount from known x402 requirement shapes."""
        for atomic_key in ("maxAmountRequired", "maxAmount", "amount"):
            raw_amount = requirement.get(atomic_key)
            if raw_amount not in (None, ""):
                return float(raw_amount) / 1_000_000

        price = requirement.get("price")
        if isinstance(price, str) and price.startswith("$"):
            return float(price[1:])
        return float(price or 0)

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

            payment_required = self._decode_payment_required(str(payment_required_raw))
            requirement = self._select_payment_requirement(payment_required)

            # Extract amount and check against budget
            amount = self._extract_amount_usd(requirement)
            recipient = requirement.get("payTo") or requirement.get("pay_to") or ""

            if amount > budget_remaining:
                return PaymentResult(
                    success=False,
                    protocol="x402",
                    amount_usd=amount,
                    recipient=recipient,
                    error=f"Payment ${amount:.4f} exceeds remaining budget ${budget_remaining:.2f}",
                )

            client = self._get_client()
            http_client_cls = import_module("x402.http").x402HTTPClient
            x402_httpx_client_cls = import_module("x402.http.clients").x402HttpxClient

            async with x402_httpx_client_cls(client) as http_client:
                request_kwargs: dict[str, Any] = {
                    "method": method,
                    "url": url,
                    "headers": headers or None,
                }
                if body is not None:
                    if isinstance(body, dict | list):
                        request_kwargs["json"] = body
                    else:
                        request_kwargs["content"] = body
                response = await http_client.request(**request_kwargs)
                await response.aread()

            if 200 <= response.status_code < 300:
                # Extract tx hash from response headers if available
                payment_response = response.headers.get("PAYMENT-RESPONSE", "")
                tx_hash = None
                if payment_response:
                    try:
                        pr_data = json.loads(base64.b64decode(payment_response))
                        tx_hash = pr_data.get("txHash") or pr_data.get("transaction_hash")
                    except Exception:
                        logger.debug("Failed to parse x402 PAYMENT-RESPONSE header")
                try:
                    settle_response = http_client_cls(client).get_payment_settle_response(
                        lambda name: response.headers.get(name)
                    )
                    if settle_response is not None:
                        tx_hash = tx_hash or getattr(settle_response, "tx_hash", None)
                except Exception:
                    logger.debug("Failed to parse x402 settle response")

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
