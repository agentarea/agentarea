"""Optional live testnet smoke tests for x402 and MPP payments.

These tests are skipped unless explicit endpoints and throwaway funded keys are
provided via environment variables. They are intentionally outside the default
CI contract and are meant for release/manual verification.
"""

from __future__ import annotations

import json
import os
from typing import Any

import httpx
import pytest

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


def _request_body(prefix: str) -> Any | None:
    raw = os.getenv(f"{prefix}_BODY")
    if not raw:
        return None
    return json.loads(raw)


async def _initial_402(url: str, method: str, body: Any | None) -> httpx.Response:
    request_kwargs: dict[str, Any] = {"method": method, "url": url}
    if body is not None:
        if isinstance(body, dict | list):
            request_kwargs["json"] = body
        else:
            request_kwargs["content"] = body
    async with httpx.AsyncClient(timeout=30.0) as client:
        return await client.request(**request_kwargs)


async def test_x402_base_sepolia_smoke():
    url = os.getenv("AGENTAREA_X402_TESTNET_URL")
    private_key = os.getenv("AGENTAREA_X402_PRIVATE_KEY")
    if not url or not private_key:
        pytest.skip("Set AGENTAREA_X402_TESTNET_URL and AGENTAREA_X402_PRIVATE_KEY")

    from agentarea_payment.x402_client import X402PaymentClient

    method = os.getenv("AGENTAREA_X402_TESTNET_METHOD", "GET")
    body = _request_body("AGENTAREA_X402_TESTNET")
    first = await _initial_402(url, method, body)
    assert first.status_code == 402
    assert first.headers.get("PAYMENT-REQUIRED") or first.headers.get("payment-required")

    client = X402PaymentClient(
        private_key=private_key,
        network=os.getenv("AGENTAREA_X402_NETWORK", "eip155:84532"),
        facilitator_url=os.getenv("AGENTAREA_X402_FACILITATOR", "https://x402.org/facilitator"),
    )
    result = await client.handle_402(
        url=url,
        method=method,
        headers={},
        body=body,
        response_headers=dict(first.headers),
        budget_remaining=float(os.getenv("AGENTAREA_X402_TESTNET_BUDGET", "1.0")),
    )

    assert result.success is True, result.error
    assert result.protocol == "x402"
    assert result.response_status is not None
    assert 200 <= result.response_status < 300


async def test_mpp_tempo_testnet_smoke():
    url = os.getenv("AGENTAREA_MPP_TESTNET_URL")
    tempo_key = os.getenv("AGENTAREA_MPP_TEMPO_KEY")
    if not url or not tempo_key:
        pytest.skip("Set AGENTAREA_MPP_TESTNET_URL and AGENTAREA_MPP_TEMPO_KEY")

    from agentarea_payment.mpp_client import MPPPaymentClient

    method = os.getenv("AGENTAREA_MPP_TESTNET_METHOD", "GET")
    body = _request_body("AGENTAREA_MPP_TESTNET")
    first = await _initial_402(url, method, body)
    assert first.status_code == 402
    assert first.headers.get("WWW-Authenticate") or first.headers.get("www-authenticate")

    client = MPPPaymentClient(
        tempo_key=tempo_key,
        session_budget_usd=float(os.getenv("AGENTAREA_MPP_TESTNET_BUDGET", "1.0")),
        chain_id=int(os.getenv("AGENTAREA_MPP_CHAIN_ID"))
        if os.getenv("AGENTAREA_MPP_CHAIN_ID")
        else None,
        rpc_url=os.getenv("AGENTAREA_MPP_RPC_URL"),
        currency=os.getenv("AGENTAREA_MPP_CURRENCY"),
        recipient=os.getenv("AGENTAREA_MPP_RECIPIENT"),
    )
    result = await client.handle_402(
        url=url,
        method=method,
        headers={},
        body=body,
        response_headers=dict(first.headers),
        response_body=first.text,
        budget_remaining=float(os.getenv("AGENTAREA_MPP_TESTNET_BUDGET", "1.0")),
    )

    assert result.success is True, result.error
    assert result.protocol == "mpp"
    assert result.response_status is not None
    assert 200 <= result.response_status < 300
