"""MPP (Machine Payments Protocol) client."""

from __future__ import annotations

import logging
from importlib import import_module
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
        chain_id: int | None = None,
        rpc_url: str | None = None,
        currency: str | None = None,
        recipient: str | None = None,
        decimals: int = 6,
    ):
        self._tempo_key = tempo_key
        self._session_budget_usd = session_budget_usd
        self._payment_method_types = payment_method_types or ["charge"]
        self._chain_id = chain_id
        self._rpc_url = rpc_url
        self._currency = currency
        self._recipient = recipient
        self._decimals = decimals
        self._client = None

    async def _get_client(self):
        """Lazily initialize the MPP client."""
        if self._client is not None:
            return self._client

        try:
            client_cls = import_module("mpp.client").Client
            tempo_module = import_module("mpp.methods.tempo")
            charge_intent_cls = tempo_module.ChargeIntent
            tempo_account_cls = tempo_module.TempoAccount
            tempo = tempo_module.tempo

            account = tempo_account_cls.from_key(self._tempo_key)
            client = client_cls(
                methods=[
                    tempo(
                        account=account,
                        intents={
                            "charge": charge_intent_cls(
                                chain_id=self._chain_id,
                                rpc_url=self._rpc_url,
                            )
                        },
                        chain_id=self._chain_id,
                        rpc_url=self._rpc_url,
                        currency=self._currency,
                        recipient=self._recipient,
                    )
                ]
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
            challenge_data: dict[str, Any] = {}
            www_auth = response_headers.get("WWW-Authenticate") or response_headers.get(
                "www-authenticate"
            )
            if www_auth:
                try:
                    parse_www_authenticate = import_module("mpp").parse_www_authenticate
                    challenge = parse_www_authenticate(www_auth)
                    challenge_data = dict(getattr(challenge, "request", {}) or {})
                    challenge_data.setdefault("method", getattr(challenge, "method", None))
                    challenge_data.setdefault("intent", getattr(challenge, "intent", None))
                except Exception:
                    logger.debug("Failed to parse MPP WWW-Authenticate challenge")

            if not challenge_data:
                challenge_data = (
                    json.loads(response_body)
                    if isinstance(response_body, str | bytes)
                    else response_body
                )
                if not isinstance(challenge_data, dict):
                    challenge_data = {}

            amount = self._amount_usd(challenge_data.get("amount", 0))
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
            response = await client.request(
                **request_kwargs,
            )

            tx_hash = None
            receipt = response.headers.get("X-MPP-Receipt") or response.headers.get("x-mpp-receipt")
            if receipt:
                try:
                    parse_payment_receipt = import_module("mpp").parse_payment_receipt
                    receipt_data = parse_payment_receipt(receipt)
                    tx_hash = getattr(receipt_data, "external_id", None) or getattr(
                        receipt_data, "reference", None
                    )
                except Exception:
                    try:
                        receipt_data = json.loads(receipt)
                        tx_hash = receipt_data.get("txHash") or receipt_data.get(
                            "transactionHash"
                        )
                    except Exception:
                        logger.debug("Failed to parse MPP receipt header")

            if 200 <= response.status_code < 300:
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

    def _amount_usd(self, raw_amount: Any) -> float:
        return float(raw_amount or 0) / (10**self._decimals)
