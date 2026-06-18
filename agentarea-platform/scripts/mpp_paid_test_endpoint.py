"""Local MPP paid endpoint for AgentArea payment-flow testing.

Run:
    uv run --with fastapi --with uvicorn --with 'pympp[tempo]' \
      python scripts/mpp_paid_test_endpoint.py --port 8787

Then point an AgentArea OpenAPI connection at:
    http://127.0.0.1:8787/openapi.json

The paid operation is:
    GET http://127.0.0.1:8787/paid/mpp

First request returns HTTP 402 with a valid MPP ``WWW-Authenticate: Payment ...``
challenge. A retry carrying ``Authorization: Payment ...`` returns 200.
This endpoint intentionally does not verify a real Tempo transaction; it is a
local flow harness for proving AgentArea detects a payment challenge, spends
from the configured service budget, retries, and records ``PaymentRecord``.
"""

from __future__ import annotations

import argparse
import os
from decimal import Decimal
from typing import Annotated

from fastapi import FastAPI, Header, Query, Response

PATH_USD_TESTNET = "0x20c0000000000000000000000000000000000000"
DEFAULT_RECIPIENT = "0x0000000000000000000000000000000000000001"


def _base_units(amount_usd: Decimal, decimals: int) -> str:
    multiplier = Decimal(10) ** decimals
    value = amount_usd * multiplier
    if value != value.to_integral_value():
        raise ValueError(f"amount {amount_usd} cannot be represented with {decimals} decimals")
    return str(int(value))


def _payment_challenge(
    *,
    amount_usd: Decimal,
    decimals: int,
    currency: str,
    recipient: str,
    realm: str,
    secret_key: str,
) -> str:
    from mpp.client.transport import Challenge

    challenge = Challenge.create(
        secret_key=secret_key,
        realm=realm,
        method="tempo",
        intent="charge",
        request={
            "amount": _base_units(amount_usd, decimals),
            "currency": currency,
            "recipient": recipient,
        },
        description=f"AgentArea local MPP test charge: ${amount_usd}",
    )
    return challenge.to_www_authenticate(realm)


def create_app() -> FastAPI:
    app = FastAPI(
        title="AgentArea MPP Paid Test Endpoint",
        version="0.1.0",
        description="Local MPP 402 challenge endpoint for AgentArea payment testing.",
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.api_route("/paid/mpp", methods=["GET", "POST"], operation_id="call_paid_mpp_tool")
    async def paid_mpp(
        response: Response,
        authorization: Annotated[str | None, Header()] = None,
        amount_usd: Annotated[
            Decimal,
            Query(description="Human USD amount for the MPP challenge."),
        ] = Decimal(os.getenv("AGENTAREA_MPP_TEST_AMOUNT_USD", "0.25")),
        decimals: Annotated[int, Query(ge=0, le=18)] = int(
            os.getenv("AGENTAREA_MPP_TEST_DECIMALS", "6")
        ),
        currency: Annotated[str, Query()] = os.getenv(
            "AGENTAREA_MPP_TEST_CURRENCY", PATH_USD_TESTNET
        ),
        recipient: Annotated[str, Query()] = os.getenv(
            "AGENTAREA_MPP_TEST_RECIPIENT", DEFAULT_RECIPIENT
        ),
        realm: Annotated[str, Query()] = os.getenv(
            "AGENTAREA_MPP_TEST_REALM", "agentarea-mpp-test.local"
        ),
    ) -> dict[str, object]:
        if authorization and authorization.lower().startswith("payment "):
            return {
                "ok": True,
                "paid": True,
                "protocol": "mpp",
                "amount_usd": float(amount_usd),
                "amount_base_units": _base_units(amount_usd, decimals),
                "currency": currency,
                "recipient": recipient,
                "authorization_received": True,
            }

        response.status_code = 402
        response.headers["WWW-Authenticate"] = _payment_challenge(
            amount_usd=amount_usd,
            decimals=decimals,
            currency=currency,
            recipient=recipient,
            realm=realm,
            secret_key=os.getenv("AGENTAREA_MPP_TEST_SECRET", "agentarea-local-mpp-secret"),
        )
        return {
            "ok": False,
            "paid": False,
            "error": "payment_required",
            "protocol": "mpp",
            "amount_usd": float(amount_usd),
            "amount_base_units": _base_units(amount_usd, decimals),
            "currency": currency,
            "recipient": recipient,
        }

    return app


app = create_app()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run local AgentArea MPP paid test endpoint.")
    parser.add_argument("--host", default=os.getenv("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "8787")))
    args = parser.parse_args()

    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
