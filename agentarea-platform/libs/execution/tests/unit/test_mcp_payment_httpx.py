"""Tests for MCP payment-aware HTTPX factory."""

from types import SimpleNamespace

import httpx
import pytest
from agentarea_execution.activities.mcp_payment_httpx import (
    AgentAreaPaymentTransport,
    create_payment_httpx_client_factory,
)


async def test_payment_httpx_factory_uses_agentarea_payment_transport():
    factory = create_payment_httpx_client_factory(
        wallet_config={"wallet_type": "dual"},
        budget_remaining=1.0,
    )

    client = factory(headers={"X-Test": "1"}, timeout=httpx.Timeout(5.0))
    try:
        assert isinstance(client._transport, AgentAreaPaymentTransport)
        assert client.headers["X-Test"] == "1"
    finally:
        await client.aclose()


class SequenceTransport(httpx.AsyncBaseTransport):
    def __init__(self, responses: list[httpx.Response]):
        self.responses = responses
        self.requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        response = self.responses.pop(0)
        return httpx.Response(
            response.status_code,
            headers=response.headers,
            content=response.content,
            request=request,
        )


@pytest.mark.asyncio
async def test_x402_transport_retries_and_reports_payment(monkeypatch):
    from agentarea_payment.x402_client import X402PaymentClient

    class FakeHTTPClient:
        def __init__(self, client):
            self.client = client

        def get_payment_required_response(self, get_header, body):
            assert get_header("PAYMENT-REQUIRED") == "challenge"
            return SimpleNamespace(
                accepts=[
                    SimpleNamespace(
                        amount="250000",
                        pay_to="0xrecipient",
                        network="eip155:84532",
                        scheme="exact",
                        get_amount=lambda: "250000",
                    )
                ]
            )

        def encode_payment_signature_header(self, payment_payload):
            assert payment_payload == {"signed": True}
            return {"PAYMENT-SIGNATURE": "signed"}

    class FakeX402Client:
        async def create_payment_payload(self, payment_required):
            return {"signed": True}

    def fake_import_module(name):
        if name == "x402.http":
            return SimpleNamespace(x402HTTPClient=FakeHTTPClient)
        raise AssertionError(name)

    monkeypatch.setattr(X402PaymentClient, "_get_client", lambda self: FakeX402Client())
    monkeypatch.setattr(
        "agentarea_execution.activities.mcp_payment_httpx.import_module",
        fake_import_module,
    )

    inner = SequenceTransport(
        [
            httpx.Response(402, headers={"PAYMENT-REQUIRED": "challenge"}, content=b"{}"),
            httpx.Response(200, content=b"ok"),
        ]
    )
    payments = []
    transport = AgentAreaPaymentTransport(
        wallet_config={
            "wallet_type": "x402",
            "x402_private_key": "0xkey",
            "x402_config": {"network": "eip155:84532"},
        },
        budget_remaining=1.0,
        on_payment=payments.append,
        inner=inner,
    )

    async with httpx.AsyncClient(transport=transport) as client:
        response = await client.get("https://paid.example/mcp")

    assert response.status_code == 200
    assert len(inner.requests) == 2
    assert inner.requests[1].headers["PAYMENT-SIGNATURE"] == "signed"
    assert payments == [
        {
            "success": True,
            "protocol": "x402",
            "amount_usd": 0.25,
            "recipient": "0xrecipient",
            "tx_hash": None,
            "response_status": 200,
            "error": None,
            "protocol_metadata": {"network": "eip155:84532", "scheme": "exact"},
            "url": "https://paid.example/mcp",
            "method": "GET",
        }
    ]


@pytest.mark.asyncio
async def test_mpp_transport_retries_and_reports_payment(monkeypatch):
    class FakeChallenge:
        method = "tempo"
        expires = None

        def __init__(self):
            self.request = {"amount": "500000", "recipient": "tempo-recipient"}

        @classmethod
        def from_www_authenticate(cls, header):
            assert header == "Payment challenge"
            return cls()

    class FakeCredential:
        def to_authorization(self):
            return "Payment credential"

    class FakeMethod:
        name = "tempo"

        async def create_credential(self, challenge):
            return FakeCredential()

    class FakeTempoAccount:
        @classmethod
        def from_key(cls, key):
            assert key == "tempo-key"
            return cls()

    def fake_tempo(**kwargs):
        return FakeMethod()

    def fake_import_module(name):
        if name == "mpp.client.transport":
            return SimpleNamespace(Challenge=FakeChallenge, ParseError=ValueError)
        if name == "mpp.methods.tempo":
            return SimpleNamespace(
                TempoAccount=FakeTempoAccount,
                ChargeIntent=lambda **kwargs: object(),
                tempo=fake_tempo,
            )
        if name == "mpp":
            return SimpleNamespace(parse_payment_receipt=lambda receipt: SimpleNamespace())
        raise AssertionError(name)

    monkeypatch.setattr(
        "agentarea_execution.activities.mcp_payment_httpx.import_module",
        fake_import_module,
    )

    inner = SequenceTransport(
        [
            httpx.Response(402, headers={"WWW-Authenticate": "Payment challenge"}, content=b""),
            httpx.Response(204, content=b""),
        ]
    )
    payments = []
    transport = AgentAreaPaymentTransport(
        wallet_config={"wallet_type": "mpp", "mpp_tempo_key": "tempo-key"},
        budget_remaining=1.0,
        on_payment=payments.append,
        inner=inner,
    )

    async with httpx.AsyncClient(transport=transport) as client:
        response = await client.post("https://paid.example/mcp", content=b"{}")

    assert response.status_code == 204
    assert len(inner.requests) == 2
    assert inner.requests[1].headers["Authorization"] == "Payment credential"
    assert payments[0]["success"] is True
    assert payments[0]["protocol"] == "mpp"
    assert payments[0]["amount_usd"] == 0.5
    assert payments[0]["recipient"] == "tempo-recipient"
