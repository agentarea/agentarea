"""Tests for the local MPP paid endpoint harness."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import httpx
import pytest

# The harness this exercises imports `mpp`, which ships in the optional
# `pympp[tempo]` extra (libs/payment/pyproject.toml). Without it the module fails
# to import, so skip rather than fail: a missing optional dependency is not a
# defect in the code under test.
pytest.importorskip("mpp", reason="requires the optional `mpp` extra: uv sync --extra mpp")


def _load_endpoint_module():
    root = Path(__file__).resolve().parents[3]
    script = root / "scripts" / "mpp_paid_test_endpoint.py"
    spec = importlib.util.spec_from_file_location("mpp_paid_test_endpoint", script)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_mpp_paid_test_endpoint_issues_parseable_challenge_and_accepts_retry():
    module = _load_endpoint_module()
    app = module.create_app()
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        first = await client.get("/paid/mpp?amount_usd=0.25")
        assert first.status_code == 402
        challenge_header = first.headers["www-authenticate"]
        assert challenge_header.startswith("Payment ")

        from mpp.client.transport import Challenge

        challenge = Challenge.from_www_authenticate(challenge_header)
        assert challenge.method == "tempo"
        assert challenge.intent == "charge"
        assert challenge.request["amount"] == "250000"

        second = await client.get(
            "/paid/mpp?amount_usd=0.25",
            headers={"Authorization": "Payment fake-local-credential"},
        )
        assert second.status_code == 200
        assert second.json()["paid"] is True
