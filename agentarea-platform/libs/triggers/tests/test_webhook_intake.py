from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from agentarea_streams.domain import AppendResult, StreamQuotaExceededError, WebhookSourceSpec
from agentarea_triggers.webhook_intake import (
    JournalAppendCallback,
    journal_data,
    webhook_event_key,
    webhook_event_kind,
)


@pytest.mark.parametrize(
    ("webhook_type", "parsed", "key"),
    [
        ("generic", {"headers": {"webhook-id": "msg_1"}}, "webhook-id:msg_1"),
        ("github", {"headers": {"X-GitHub-Delivery": "d-1"}}, "x-github-delivery:d-1"),
        ("generic", {"headers": {"Idempotency-Key": "i-1"}}, "idempotency-key:i-1"),
        ("linear", {"headers": {"linear-delivery": "l-1"}}, "linear-delivery:l-1"),
        ("telegram", {"headers": {}, "raw_data": {"update_id": 77}}, "telegram:77"),
        ("stripe", {"headers": {}, "raw_data": {"id": "evt_9"}}, "stripe:evt_9"),
        ("slack", {"headers": {}, "raw_data": {"event_id": "Ev1"}}, "slack:Ev1"),
        ("discord", {"headers": {}, "raw_data": {"id": "123"}}, "discord:123"),
    ],
)
def test_provider_delivery_ids_become_the_event_key(webhook_type, parsed, key):
    assert webhook_event_key(webhook_type, parsed) == key


def test_an_event_with_no_delivery_id_gets_a_key_that_never_repeats():
    a = webhook_event_key("generic", {"headers": {}, "raw_data": {"x": 1}})
    b = webhook_event_key("generic", {"headers": {}, "raw_data": {"x": 1}})
    assert a.startswith("recv:") and a != b


def test_kind_is_the_extracted_event_type_or_the_channel():
    assert webhook_event_kind("github", {"event_type": "push"}) == "push"
    assert webhook_event_kind("generic", {}) == "webhook.generic"


def test_credentials_in_headers_never_reach_the_journal():
    data = journal_data(
        {
            "headers": {
                "Authorization": "Bearer x",
                "X-Telegram-Bot-Api-Secret-Token": "t",
                "Cookie": "c",
                "Content-Type": "application/json",
            },
            "text": "hi",
        }
    )
    assert data["headers"] == {"Content-Type": "application/json"}
    assert data["text"] == "hi"


def _spec() -> WebhookSourceSpec:
    return WebhookSourceSpec(
        id=uuid4(),
        stream_id=uuid4(),
        workspace_id="w",
        created_by="u",
        webhook_id="wh",
        webhook_type="generic",
        allowed_methods=["POST"],
        validation_rules={},
        webhook_config=None,
        credential_key=uuid4(),
    )


async def test_the_callback_appends_and_keeps_the_receipt():
    journal = AsyncMock()
    journal.append.return_value = AppendResult(sequence=5, appended=True)
    spec = _spec()
    callback = JournalAppendCallback(journal=journal, spec=spec, source_id=uuid4())
    await callback.execute_webhook_trigger("wh", {"headers": {"webhook-id": "m"}, "text": "x"})
    event = journal.append.await_args.args[1]
    assert journal.append.await_args.kwargs["event_key"] == "webhook-id:m"
    assert event.type == "webhook.generic"
    assert event.subject == "wh"
    assert callback.receipt == AppendResult(sequence=5, appended=True)


async def test_the_callback_remembers_a_refusal_and_reraises():
    journal = AsyncMock()
    journal.append.side_effect = StreamQuotaExceededError("w", 1)
    callback = JournalAppendCallback(journal=journal, spec=_spec(), source_id=uuid4())
    with pytest.raises(StreamQuotaExceededError):
        await callback.execute_webhook_trigger("wh", {"headers": {}})
    assert isinstance(callback.refusal, StreamQuotaExceededError)
    assert callback.failure is None


async def test_the_callback_remembers_a_storage_failure_apart_from_a_refusal():
    journal = AsyncMock()
    journal.append.side_effect = ConnectionResetError("db went away")
    callback = JournalAppendCallback(journal=journal, spec=_spec(), source_id=uuid4())
    with pytest.raises(ConnectionResetError):
        await callback.execute_webhook_trigger("wh", {"headers": {}})
    assert isinstance(callback.failure, ConnectionResetError)
    assert callback.refusal is None


def test_credentials_in_query_parameters_never_reach_the_journal():
    data = journal_data(
        {
            "headers": {"X-Gitlab-Token": "g", "X-GitHub-Event": "push"},
            "query_params": {
                "token": "t",
                "key": "k",
                "secret": "s",
                "signature": "x",
                "sig": "y",
                "access_token": "a",
                "api_key": "b",
                "hub.verify_token": "v",
                "page": "2",
            },
        }
    )
    assert data["query_params"] == {"page": "2"}
    assert data["headers"] == {"X-GitHub-Event": "push"}
