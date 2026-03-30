"""Handles 402 payment responses in MCP tool execution."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def handle_402_payment(
    url: str,
    method: str,
    request_headers: dict[str, str],
    request_body: Any | None,
    response_status: int,
    response_headers: dict[str, str],
    response_body: str | bytes,
    wallet_config: dict[str, Any],
    budget_remaining: float,
) -> dict[str, Any] | None:
    """Attempt to handle a 402 response by paying via x402 or MPP.

    Args:
        url: Original request URL
        method: HTTP method
        request_headers: Original request headers
        request_body: Original request body
        response_status: 402 status code
        response_headers: 402 response headers
        response_body: 402 response body
        wallet_config: Wallet configuration dict with keys:
            - wallet_type: "x402", "mpp", "dual"
            - x402_config: dict with network, facilitator_url, signer_type
            - mpp_config: dict with payment_method_types, session_budget_usd
            - x402_private_key: decrypted private key (if x402)
            - mpp_tempo_key: decrypted tempo key (if mpp)
        budget_remaining: Remaining service budget in USD

    Returns:
        Dict with payment result info, or None if payment not possible.
    """
    if response_status != 402:
        return None

    if not wallet_config:
        logger.debug("No wallet configured, cannot handle 402")
        return None

    if budget_remaining <= 0:
        logger.warning("Service budget exhausted, cannot handle 402")
        return {
            "success": False,
            "protocol": "unknown",
            "amount_usd": 0,
            "recipient": "",
            "error": "Service budget exhausted",
        }

    try:
        from agentarea_payment import UnifiedPaymentClient

        client = UnifiedPaymentClient(
            wallet_type=wallet_config.get("wallet_type", ""),
            x402_config=wallet_config.get("x402_config"),
            mpp_config=wallet_config.get("mpp_config"),
            x402_private_key=wallet_config.get("x402_private_key"),
            mpp_tempo_key=wallet_config.get("mpp_tempo_key"),
        )

        result = await client.handle_402(
            url=url,
            method=method,
            request_headers=request_headers,
            request_body=request_body,
            response_status=response_status,
            response_headers=response_headers,
            response_body=response_body,
            budget_remaining=budget_remaining,
        )

        return {
            "success": result.success,
            "protocol": result.protocol,
            "amount_usd": result.amount_usd,
            "recipient": result.recipient,
            "tx_hash": result.tx_hash,
            "response_body": result.response_body,
            "response_status": result.response_status,
            "error": result.error,
            "protocol_metadata": result.protocol_metadata,
        }
    except ImportError:
        logger.warning("Payment library not available, cannot handle 402")
        return {
            "success": False,
            "protocol": "unknown",
            "amount_usd": 0,
            "recipient": "",
            "error": "Payment library not installed",
        }
    except Exception as e:
        logger.exception("Error handling 402 payment")
        return {
            "success": False,
            "protocol": "unknown",
            "amount_usd": 0,
            "recipient": "",
            "error": str(e),
        }
