"""MCP Events (SEP-3415) on a stream: arguments, cursors, secrets, identity, signatures."""

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError
from agentarea_streams.domain.enums import SubscriptionKind
from agentarea_streams.domain.filters import EventFilter, ExternalFilter, filter_for
from agentarea_streams.domain.mcp_events import (
    MAX_TTL,
    MIN_TTL,
    ErrorCode,
    EventArguments,
    EventsError,
    PollCursor,
    control_message_id,
    event_name,
    grant_refresh_before,
    occurrence,
    parse_event_name,
    payload_schema,
    sign,
    subscription_id,
    validate_secret,
)
from agentarea_streams.domain.models import StreamEvent

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)


def _event(**overrides) -> StreamEvent:
    values = {
        "type": "order.created",
        "source": "webhook:demo",
        "data": {"headers": {}, "body": {"id": 7}},
        "stream_id": uuid4(),
        "workspace_id": "ws-1",
        "created_by": "user-1",
        "event_key": "order:7",
        "received_at": NOW,
        "source_type": "generic_webhook",
        "session_key": "src:chat-1",
    }
    values.update(overrides)
    return StreamEvent(**values)


def _whsec(size: int = 32) -> str:
    return "whsec_" + base64.b64encode(b"k" * size).decode()


def test_arguments_become_a_filter_on_kind_source_type_and_session():
    arguments = EventArguments.model_validate(
        {"kind": "order", "source_type": "generic_webhook", "session_key": "src:chat-1"}
    )
    admits = arguments.to_filter().admits
    assert admits(_event())
    assert not admits(_event(type="invoice.paid"))
    assert not admits(_event(source_type="github"))
    assert not admits(_event(session_key="src:chat-2"))
    assert EventArguments().to_filter().admits(_event(source_type=None, session_key=None))


def test_unknown_arguments_are_refused():
    with pytest.raises(ValidationError):
        EventArguments.model_validate({"severity": "P1"})


def test_arguments_compare_by_their_canonical_form():
    assert (
        EventArguments.model_validate({"kind": "a", "session_key": None}).canonical()
        == EventArguments.model_validate({"kind": "a"}).canonical()
    )


def test_an_external_subscription_reads_its_own_filter_back():
    stored = ExternalFilter(kinds=["order"], source_type="github").model_dump()
    assert isinstance(filter_for(SubscriptionKind.EXTERNAL, stored), ExternalFilter)
    assert type(filter_for(SubscriptionKind.TRIGGER, {"kinds": ["x"]})) is EventFilter
    with pytest.raises(ValidationError):
        filter_for(SubscriptionKind.TRIGGER, stored)


def test_a_trigger_filter_still_admits_by_kind_and_fields():
    assert EventFilter(kinds=["order"]).admits(_event())
    assert not EventFilter(fields={"body.id": 8}).admits(_event())


def test_a_poll_cursor_round_trips_and_is_opaque():
    cursor = PollCursor(at=NOW, sequence=41)
    text = cursor.encode()
    assert "41" not in text
    assert PollCursor.decode(text) == cursor


@pytest.mark.parametrize("text", ["", "nonsense", base64.urlsafe_b64encode(b"v9:1:2").decode()])
def test_a_foreign_cursor_is_invalid_params(text):
    with pytest.raises(EventsError) as raised:
        PollCursor.decode(text)
    assert raised.value.code == ErrorCode.INVALID_PARAMS


def test_a_cursor_older_than_the_window_is_truncated():
    window_start = NOW - timedelta(days=7)
    assert PollCursor(at=window_start - timedelta(seconds=1), sequence=1).before(window_start)
    assert not PollCursor(at=window_start, sequence=1).before(window_start)


@pytest.mark.parametrize("size", [24, 32, 64])
def test_a_standard_webhooks_secret_is_accepted(size):
    validate_secret(_whsec(size))


@pytest.mark.parametrize(
    "secret",
    [
        "plain-text",
        "whsec_",
        "whsec_not base64!",
        "whsec_" + base64.b64encode(b"k" * 23).decode(),
        "whsec_" + base64.b64encode(b"k" * 65).decode(),
    ],
)
def test_any_other_secret_is_invalid_params(secret):
    with pytest.raises(EventsError) as raised:
        validate_secret(secret)
    assert raised.value.code == ErrorCode.INVALID_PARAMS


def test_the_subscription_id_is_derived_from_the_whole_key():
    stream = uuid4()
    args = EventArguments(kind="order")
    first = subscription_id("user:1", "https://hooks.example/a", stream, args)
    assert first == subscription_id("user:1", "https://hooks.example/a", stream, args)
    assert first.startswith("sub_")
    others = {
        subscription_id("user:2", "https://hooks.example/a", stream, args),
        subscription_id("user:1", "https://hooks.example/b", stream, args),
        subscription_id("user:1", "https://hooks.example/a", uuid4(), args),
        subscription_id("user:1", "https://hooks.example/a", stream, EventArguments()),
    }
    assert first not in others
    assert len(others) == 4


def test_the_signature_is_the_standard_webhooks_v1_hmac():
    # The Standard Webhooks specification's reference vector.
    secret = "whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw"  # noqa: S105 - the published test vector  # pragma: allowlist secret
    body = b'{"test": 2432232314}'
    signature = sign(secret, "msg_p5jXN8AQM9LWM0D4loKWxJek", 1614265330, body)
    key = base64.b64decode(secret.removeprefix("whsec_"))
    expected = base64.b64encode(
        hmac.new(key, b"msg_p5jXN8AQM9LWM0D4loKWxJek.1614265330." + body, hashlib.sha256).digest()
    ).decode()
    assert signature == f"v1,{expected}"
    assert signature == "v1,g0hM9SsE+OTPJTGt/tmIKtSyZlE3uFJELVlNIOLJ1OE="


def test_a_control_message_id_names_its_type():
    assert control_message_id("verification").startswith("msg_verification_")
    assert control_message_id("gap") != control_message_id("gap")


def test_the_granted_ttl_never_exceeds_the_suggestion_and_has_bounds():
    assert grant_refresh_before(600_000, now=NOW) == NOW + timedelta(minutes=10)
    assert grant_refresh_before(1, now=NOW) == NOW + MIN_TTL
    assert grant_refresh_before(10**12, now=NOW) == NOW + MAX_TTL
    # No expiry is not granted: a finite grant is the answer to ttlMs: null.
    assert grant_refresh_before(None, now=NOW) == NOW + MAX_TTL


def test_an_occurrence_carries_the_envelope_as_data():
    event = _event()
    body = occurrence(event, "orders")
    assert body["eventId"] == str(event.id)
    assert body["name"] == "orders"
    assert body["timestamp"] == event.time.isoformat()
    data = body["data"]
    assert data["v"] == 1
    assert data["kind"] == "order.created"
    assert data["key"] == "order:7"
    assert data["session_key"] == "src:chat-1"
    assert data["data"] == {"headers": {}, "body": {"id": 7}}
    json.dumps(body)
    assert set(data) <= set(payload_schema()["properties"])


def test_an_event_name_carries_its_workspace_and_stream():
    stream = uuid4()
    assert parse_event_name(event_name("lv-delivery", stream)) == ("lv-delivery", stream)


@pytest.mark.parametrize("name", ["", "lv-delivery", "lv-delivery/not-a-uuid", "/" + str(uuid4())])
def test_an_unknown_event_name_is_not_found(name):
    with pytest.raises(EventsError) as raised:
        parse_event_name(name)
    assert raised.value.code == ErrorCode.NOT_FOUND
    assert raised.value.data == {"kind": "event"}
