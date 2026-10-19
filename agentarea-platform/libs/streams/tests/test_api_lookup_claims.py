"""An api_lookup notification is believed only in the state the provider's API holds.

A lookup entry: the state an event name claims must be the fetched object's (or
one it has moved on to), the lookup URL carries body values as one path segment
each, and what is recorded is the fetched object.
"""

import json
from pathlib import Path

from agentarea_streams.domain.source_types import SourceTypeEntry


import json
from uuid import uuid4

import pytest
from agentarea_streams.domain.envelope import read_event
from agentarea_streams.domain.verification import VerificationError, verify_request

ENTRY = SourceTypeEntry.model_validate(
    json.loads((Path(__file__).parent / "example_pay.json").read_text())
)

assert ENTRY.verification is not None
SCHEME = ENTRY.verification


def _fetching(fetched, calls=None):
    async def lookup(method, url, auth):
        if calls is not None:
            calls.append(url)
        return 200, fetched

    return lookup


async def _verify(body, fetched, calls=None):
    return await verify_request(
        SCHEME,
        headers={},
        raw_body=json.dumps(body).encode(),
        body=body,
        credentials={"secret_key": "live_x"},
        config={"shop_id": "42"},
        lookup=_fetching(fetched, calls),
    )


async def test_a_pending_payment_notified_as_succeeded_is_refused():
    forged = {"event": "payment.succeeded", "object": {"id": "p1", "status": "pending"}}
    with pytest.raises(VerificationError):
        await _verify(forged, {"id": "p1", "status": "pending"})


@pytest.mark.parametrize(
    ("event", "status"),
    [
        ("payment.succeeded", "succeeded"),
        ("payment.waiting_for_capture", "waiting_for_capture"),
        ("payment.canceled", "canceled"),
        ("refund.succeeded", "succeeded"),
    ],
)
async def test_the_state_an_event_claims_is_the_state_verified(event, status):
    body = {"event": event, "object": {"id": "p1", "status": status}}
    await _verify(body, {"id": "p1", "status": status})
    claimed_elsewhere = {"event": event, "object": {"id": "p1", "status": "pending"}}
    with pytest.raises(VerificationError):
        await _verify(claimed_elsewhere, {"id": "p1", "status": "pending"})


async def test_a_canceled_payment_notified_as_succeeded_is_refused():
    body = {"event": "payment.succeeded", "object": {"id": "p1", "status": "canceled"}}
    with pytest.raises(VerificationError):
        await _verify(body, {"id": "p1", "status": "canceled"})


async def test_what_is_recorded_is_the_fetched_object():
    notified = {
        "event": "payment.waiting_for_capture",
        "object": {"id": "p1", "status": "waiting_for_capture", "amount": {"value": "999.00"}},
    }
    fetched = {"id": "p1", "status": "succeeded", "amount": {"value": "2.00"}}
    verified = await _verify(notified, fetched)
    assert verified["object"] == fetched
    fields = read_event(ENTRY, None, source_id=uuid4(), headers={}, body=verified)
    assert fields.kind == "payment.succeeded"
    assert fields.key == "payment.succeeded:p1"


@pytest.mark.parametrize("object_id", ["abc?limit=100", "a/b/c", "abc#"])
async def test_a_body_value_fills_one_path_segment_of_the_lookup_url(object_id):
    calls: list[str] = []
    body = {"event": "payment.succeeded", "object": {"id": object_id, "status": "succeeded"}}
    await _verify(body, {"id": object_id, "status": "succeeded"}, calls)
    [url] = calls
    path = url.removeprefix("https://api.payments.example/v3/payments/")
    assert "?" not in url
    assert "#" not in url
    assert "/" not in path
