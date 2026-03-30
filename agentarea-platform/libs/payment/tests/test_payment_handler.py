"""Integration tests for 402 payment interception handler."""

import pytest

from agentarea_execution.activities.payment_handler import handle_402_payment


class TestHandle402Payment:
    @pytest.mark.asyncio
    async def test_non_402_returns_none(self):
        result = await handle_402_payment(
            url="https://api.example.com",
            method="GET",
            request_headers={},
            request_body=None,
            response_status=200,
            response_headers={},
            response_body="",
            wallet_config={},
            budget_remaining=5.0,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_no_wallet_returns_none(self):
        result = await handle_402_payment(
            url="https://api.example.com",
            method="GET",
            request_headers={},
            request_body=None,
            response_status=402,
            response_headers={"PAYMENT-REQUIRED": "data"},
            response_body="",
            wallet_config={},
            budget_remaining=5.0,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_exhausted_budget_returns_error(self):
        result = await handle_402_payment(
            url="https://api.example.com",
            method="GET",
            request_headers={},
            request_body=None,
            response_status=402,
            response_headers={"PAYMENT-REQUIRED": "data"},
            response_body="",
            wallet_config={"wallet_type": "x402"},
            budget_remaining=0.0,
        )
        assert result is not None
        assert result["success"] is False
        assert "exhausted" in result["error"]

    @pytest.mark.asyncio
    async def test_missing_payment_lib_returns_error(self):
        """When agentarea_payment is not importable, returns graceful error."""
        # This test works because we don't have x402/pympp SDKs installed in test env
        result = await handle_402_payment(
            url="https://api.example.com",
            method="GET",
            request_headers={},
            request_body=None,
            response_status=402,
            response_headers={"PAYMENT-REQUIRED": "data"},
            response_body="",
            wallet_config={
                "wallet_type": "x402",
                "x402_config": {"network": "eip155:8453"},
                "x402_private_key": "0xfakekey",
            },
            budget_remaining=5.0,
        )
        assert result is not None
        assert result["success"] is False
        # Either "not installed" or an SDK import error
        assert result["error"] is not None
