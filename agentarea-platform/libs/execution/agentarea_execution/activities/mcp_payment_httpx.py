"""Payment-aware HTTPX transport for MCP URL clients."""

from __future__ import annotations

import base64
import inspect
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from importlib import import_module
from typing import Any

import httpx

logger = logging.getLogger(__name__)

PaymentCallback = Callable[[dict[str, Any]], Awaitable[None] | None]


def create_payment_httpx_client_factory(
    *,
    wallet_config: dict[str, Any],
    budget_remaining: float,
    on_payment: PaymentCallback | None = None,
):
    """Create an MCP-compatible httpx client factory with payment retry support."""

    def factory(
        headers: dict[str, str] | None = None,
        timeout: httpx.Timeout | None = None,
        auth: httpx.Auth | None = None,
    ) -> httpx.AsyncClient:
        kwargs: dict[str, Any] = {
            "follow_redirects": True,
            "transport": AgentAreaPaymentTransport(
                wallet_config=wallet_config,
                budget_remaining=budget_remaining,
                on_payment=on_payment,
            ),
        }
        if timeout is not None:
            kwargs["timeout"] = timeout
        if headers is not None:
            kwargs["headers"] = headers
        if auth is not None:
            kwargs["auth"] = auth
        return httpx.AsyncClient(**kwargs)

    return factory


class AgentAreaPaymentTransport(httpx.AsyncBaseTransport):
    """HTTPX transport that pays x402/MPP 402 challenges and tracks spend."""

    RETRY_KEY = "_agentarea_payment_retry"

    def __init__(
        self,
        *,
        wallet_config: dict[str, Any],
        budget_remaining: float,
        on_payment: PaymentCallback | None = None,
        inner: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._wallet_config = wallet_config
        self._budget_remaining = float(budget_remaining)
        self._on_payment = on_payment
        self._inner = inner or httpx.AsyncHTTPTransport()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await self._inner.handle_async_request(request)
        if response.status_code != 402 or request.extensions.get(self.RETRY_KEY):
            return response

        await response.aread()
        headers = dict(response.headers)
        protocol = self._detect_protocol(headers)
        if protocol == "x402":
            return await self._handle_x402(request, response)
        if protocol == "mpp":
            return await self._handle_mpp(request, response)
        return response

    async def aclose(self) -> None:
        await self._inner.aclose()

    @staticmethod
    def _detect_protocol(headers: dict[str, str]) -> str | None:
        lower = {k.lower(): v for k, v in headers.items()}
        if "payment-required" in lower:
            return "x402"
        www_auth = lower.get("www-authenticate", "").lower()
        if www_auth.startswith("payment") or "mpp" in www_auth:
            return "mpp"
        return None

    async def _handle_x402(
        self, request: httpx.Request, response: httpx.Response
    ) -> httpx.Response:
        if self._wallet_config.get("wallet_type") not in {"x402", "dual"}:
            return response
        private_key = self._wallet_config.get("x402_private_key")
        if not private_key:
            return response

        try:
            from agentarea_payment.x402_client import X402PaymentClient

            x402_config = self._wallet_config.get("x402_config") or {}
            client = X402PaymentClient(
                private_key=private_key,
                network=x402_config.get("network", "eip155:8453"),
                facilitator_url=x402_config.get("facilitator_url", "https://x402.org/facilitator"),
                signer_type=x402_config.get("signer_type", "evm"),
            )._get_client()
            http_client_cls = import_module("x402.http").x402HTTPClient
            http_client = http_client_cls(client)

            body = self._json_body(response)
            payment_required = http_client.get_payment_required_response(
                lambda name: response.headers.get(name), body
            )
            requirement = self._select_x402_requirement(payment_required, x402_config.get("network"))
            amount = self._x402_amount_usd(requirement)
            recipient = str(getattr(requirement, "pay_to", "") or "")
            if amount > self._budget_remaining:
                await self._notify(
                    self._payment_result(
                        protocol="x402",
                        success=False,
                        amount_usd=amount,
                        recipient=recipient,
                        request=request,
                        error=(
                            f"Payment ${amount:.4f} exceeds remaining budget "
                            f"${self._budget_remaining:.2f}"
                        ),
                    )
                )
                return response

            payment_payload = await client.create_payment_payload(payment_required)
            payment_headers = http_client.encode_payment_signature_header(payment_payload)
            retry_headers = dict(request.headers)
            retry_headers.update(payment_headers)
            retry_headers["Access-Control-Expose-Headers"] = (
                "PAYMENT-RESPONSE,X-PAYMENT-RESPONSE"
            )
            retry_response = await self._inner.handle_async_request(
                self._retry_request(request, retry_headers)
            )
            success = 200 <= retry_response.status_code < 300
            if success:
                self._budget_remaining -= amount
            await self._notify(
                self._payment_result(
                    protocol="x402",
                    success=success,
                    amount_usd=amount,
                    recipient=recipient,
                    request=request,
                    response=retry_response,
                    tx_hash=self._x402_tx_hash(retry_response),
                    protocol_metadata={
                        "network": str(getattr(requirement, "network", "") or ""),
                        "scheme": str(getattr(requirement, "scheme", "") or "exact"),
                    },
                    error=None if success else f"Payment retry failed: {retry_response.status_code}",
                )
            )
            return retry_response
        except Exception as e:
            logger.exception("x402 MCP payment failed")
            await self._notify(
                self._payment_result(
                    protocol="x402",
                    success=False,
                    amount_usd=0,
                    recipient="",
                    request=request,
                    error=str(e),
                )
            )
            return response

    async def _handle_mpp(
        self, request: httpx.Request, response: httpx.Response
    ) -> httpx.Response:
        if self._wallet_config.get("wallet_type") not in {"mpp", "dual"}:
            return response
        tempo_key = self._wallet_config.get("mpp_tempo_key")
        if not tempo_key:
            return response

        try:
            transport_module = import_module("mpp.client.transport")
            challenge_cls = transport_module.Challenge
            parse_error_cls = transport_module.ParseError
            tempo_module = import_module("mpp.methods.tempo")
            mpp_config = self._wallet_config.get("mpp_config") or {}
            account = tempo_module.TempoAccount.from_key(tempo_key)
            method = tempo_module.tempo(
                account=account,
                intents={
                    "charge": tempo_module.ChargeIntent(
                        chain_id=mpp_config.get("chain_id"),
                        rpc_url=mpp_config.get("rpc_url"),
                    )
                },
                chain_id=mpp_config.get("chain_id"),
                rpc_url=mpp_config.get("rpc_url"),
                currency=mpp_config.get("currency"),
                recipient=mpp_config.get("recipient"),
            )

            challenge = None
            for header in response.headers.get_list("www-authenticate"):
                if not header.lower().startswith("payment "):
                    continue
                try:
                    parsed = challenge_cls.from_www_authenticate(header)
                except parse_error_cls:
                    continue
                if parsed.method == method.name:
                    challenge = parsed
                    break
            if not challenge:
                return response
            if challenge.expires and self._challenge_expired(challenge.expires):
                return response

            amount = self._mpp_amount_usd(
                challenge.request.get("amount", 0),
                int(mpp_config.get("decimals", 6)),
            )
            recipient = str(
                challenge.request.get("recipient") or challenge.request.get("payTo") or ""
            )
            if amount > self._budget_remaining:
                await self._notify(
                    self._payment_result(
                        protocol="mpp",
                        success=False,
                        amount_usd=amount,
                        recipient=recipient,
                        request=request,
                        error=(
                            f"Payment ${amount:.4f} exceeds remaining budget "
                            f"${self._budget_remaining:.2f}"
                        ),
                    )
                )
                return response

            credential = await method.create_credential(challenge)
            retry_headers = httpx.Headers(request.headers)
            retry_headers["Authorization"] = credential.to_authorization()
            retry_response = await self._inner.handle_async_request(
                self._retry_request(request, retry_headers)
            )
            success = 200 <= retry_response.status_code < 300
            if success:
                self._budget_remaining -= amount
            await self._notify(
                self._payment_result(
                    protocol="mpp",
                    success=success,
                    amount_usd=amount,
                    recipient=recipient,
                    request=request,
                    response=retry_response,
                    tx_hash=self._mpp_tx_hash(retry_response),
                    protocol_metadata={"payment_method": "charge"},
                    error=None if success else f"MPP retry failed: {retry_response.status_code}",
                )
            )
            return retry_response
        except Exception as e:
            logger.exception("MPP MCP payment failed")
            await self._notify(
                self._payment_result(
                    protocol="mpp",
                    success=False,
                    amount_usd=0,
                    recipient="",
                    request=request,
                    error=str(e),
                )
            )
            return response

    @staticmethod
    def _json_body(response: httpx.Response) -> dict[str, Any] | None:
        try:
            body = response.json()
        except json.JSONDecodeError:
            return None
        return body if isinstance(body, dict) else None

    @staticmethod
    def _select_x402_requirement(payment_required: Any, network: str | None) -> Any:
        accepts = getattr(payment_required, "accepts", None) or []
        if not accepts:
            return payment_required
        for requirement in accepts:
            if network and str(getattr(requirement, "network", "") or "") != network:
                continue
            return requirement
        return accepts[0]

    @staticmethod
    def _x402_amount_usd(requirement: Any) -> float:
        if hasattr(requirement, "get_amount"):
            return float(requirement.get_amount() or 0) / 1_000_000
        amount = getattr(requirement, "amount", None) or getattr(
            requirement, "max_amount_required", 0
        )
        return float(amount or 0) / 1_000_000

    @staticmethod
    def _mpp_amount_usd(raw_amount: Any, decimals: int) -> float:
        return float(raw_amount or 0) / (10**decimals)

    @staticmethod
    def _retry_request(request: httpx.Request, headers: httpx.Headers | dict[str, str]) -> httpx.Request:
        extensions = dict(request.extensions)
        extensions[AgentAreaPaymentTransport.RETRY_KEY] = True
        kwargs: dict[str, Any] = {
            "method": request.method,
            "url": request.url,
            "headers": headers,
            "extensions": extensions,
        }
        try:
            kwargs["content"] = request.content
        except httpx.RequestNotRead:
            kwargs["stream"] = request.stream
        return httpx.Request(**kwargs)

    @staticmethod
    def _x402_tx_hash(response: httpx.Response) -> str | None:
        raw = response.headers.get("PAYMENT-RESPONSE") or response.headers.get(
            "X-PAYMENT-RESPONSE"
        )
        if not raw:
            return None
        try:
            data = json.loads(base64.b64decode(raw))
            return data.get("txHash") or data.get("transaction_hash")
        except Exception:
            return None

    @staticmethod
    def _mpp_tx_hash(response: httpx.Response) -> str | None:
        receipt = response.headers.get("X-MPP-Receipt") or response.headers.get("x-mpp-receipt")
        if not receipt:
            return None
        try:
            parse_payment_receipt = import_module("mpp").parse_payment_receipt
            receipt_data = parse_payment_receipt(receipt)
            return getattr(receipt_data, "external_id", None) or getattr(receipt_data, "reference", None)
        except Exception:
            try:
                data = json.loads(receipt)
                return data.get("txHash") or data.get("transactionHash")
            except Exception:
                return None

    @staticmethod
    def _challenge_expired(expires: str) -> bool:
        try:
            return datetime.fromisoformat(expires.replace("Z", "+00:00")) < datetime.now(UTC)
        except ValueError:
            return False

    async def _notify(self, result: dict[str, Any]) -> None:
        if self._on_payment is None:
            return
        maybe = self._on_payment(result)
        if inspect.isawaitable(maybe):
            await maybe

    @staticmethod
    def _payment_result(
        *,
        protocol: str,
        success: bool,
        amount_usd: float,
        recipient: str,
        request: httpx.Request,
        response: httpx.Response | None = None,
        tx_hash: str | None = None,
        protocol_metadata: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        return {
            "success": success,
            "protocol": protocol,
            "amount_usd": amount_usd,
            "recipient": recipient,
            "tx_hash": tx_hash,
            "response_status": response.status_code if response else None,
            "error": error,
            "protocol_metadata": protocol_metadata or {},
            "url": str(request.url),
            "method": request.method,
        }
