"""Tests for payment protocol detection and unified client."""

import pytest

from agentarea_payment.detector import PaymentProtocolDetector
from agentarea_payment.models import PaymentResult


class TestPaymentProtocolDetector:
    def test_detect_x402_from_payment_required_header(self):
        result = PaymentProtocolDetector.detect(402, {"PAYMENT-REQUIRED": "base64data..."})
        assert result == "x402"

    def test_detect_x402_case_insensitive(self):
        result = PaymentProtocolDetector.detect(402, {"payment-required": "base64data..."})
        assert result == "x402"

    def test_detect_mpp_from_www_authenticate(self):
        result = PaymentProtocolDetector.detect(402, {"WWW-Authenticate": "MPP realm=test"})
        assert result == "mpp"

    def test_detect_mpp_case_insensitive(self):
        result = PaymentProtocolDetector.detect(402, {"www-authenticate": "mpp challenge=abc"})
        assert result == "mpp"

    def test_unknown_402_no_payment_headers(self):
        result = PaymentProtocolDetector.detect(402, {"Content-Type": "application/json"})
        assert result is None

    def test_non_402_returns_none(self):
        result = PaymentProtocolDetector.detect(200, {"PAYMENT-REQUIRED": "data"})
        assert result is None

    def test_empty_headers(self):
        result = PaymentProtocolDetector.detect(402, {})
        assert result is None

    def test_x402_takes_precedence_over_mpp(self):
        """If both headers present, x402 is detected first."""
        result = PaymentProtocolDetector.detect(402, {
            "PAYMENT-REQUIRED": "data",
            "WWW-Authenticate": "MPP realm=test",
        })
        assert result == "x402"


class TestPaymentResult:
    def test_successful_result(self):
        r = PaymentResult(
            success=True,
            protocol="x402",
            amount_usd=0.01,
            recipient="0xabc",
            tx_hash="0xdef",
        )
        assert r.success is True
        assert r.protocol == "x402"
        assert r.amount_usd == 0.01
        assert r.error is None

    def test_failed_result(self):
        r = PaymentResult(
            success=False,
            protocol="mpp",
            amount_usd=0.50,
            recipient="0xabc",
            error="Insufficient balance",
        )
        assert r.success is False
        assert r.error == "Insufficient balance"
        assert r.tx_hash is None


class TestUnifiedPaymentClient:
    @pytest.mark.asyncio
    async def test_unsupported_protocol_returns_error(self):
        from agentarea_payment.unified_client import UnifiedPaymentClient

        client = UnifiedPaymentClient(
            wallet_type="mpp",
            mpp_config={"payment_method_types": ["charge"]},
            mpp_tempo_key="0xkey",
        )

        # x402 402 response but wallet only supports MPP
        result = await client.handle_402(
            url="https://api.example.com/data",
            method="GET",
            request_headers={},
            request_body=None,
            response_status=402,
            response_headers={"PAYMENT-REQUIRED": "base64data"},
            response_body="",
            budget_remaining=5.0,
        )
        assert result.success is False
        assert "not support x402" in result.error

    @pytest.mark.asyncio
    async def test_unknown_protocol_returns_error(self):
        from agentarea_payment.unified_client import UnifiedPaymentClient

        client = UnifiedPaymentClient(wallet_type="dual")

        result = await client.handle_402(
            url="https://api.example.com/data",
            method="GET",
            request_headers={},
            request_body=None,
            response_status=402,
            response_headers={"Content-Type": "text/plain"},
            response_body="Pay up",
            budget_remaining=5.0,
        )
        assert result.success is False
        assert "Unknown" in result.error
