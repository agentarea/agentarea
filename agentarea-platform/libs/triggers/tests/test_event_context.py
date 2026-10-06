"""The agent is told what started its run: one block, from the event alone, never cut."""

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from agentarea_common.trigger_event_file import event_data_json
from agentarea_streams.domain import JournaledEvent
from agentarea_triggers.domain.enums import TriggerType
from agentarea_triggers.domain.models import Trigger, WebhookTrigger
from agentarea_triggers.event_context import (
    EVENT_INLINE_LIMIT_BYTES,
    TriggerEvent,
    render_event_block,
)
from agentarea_triggers.trigger_service import compose_task_input
from agentarea_triggers.webhook_intake import journal_data

RECEIVED = datetime(2026, 10, 6, 9, 30, 15, tzinfo=UTC)


def _journaled(data, *, sequence=7, kind="order.paid", key="webhook-id:evt-1"):
    return JournaledEvent(
        type=kind,
        source="webhook:generic",
        data=data,
        stream_id=uuid4(),
        sequence=sequence,
        event_key=key,
        received_at=RECEIVED,
    )


def _stream_trigger(task_text=None):
    return Trigger(
        name="Orders",
        agent_id=uuid4(),
        created_by="u",
        workspace_id="w",
        trigger_type=TriggerType.STREAM,
        task_parameters={"text": task_text} if task_text else {},
    )


def test_a_small_event_is_quoted_whole_under_its_provenance():
    data = {"order": {"id": "A-1003", "total": "12.50", "note": "Grüße"}}
    block = render_event_block(
        trigger_name="Orders",
        trigger_type="stream",
        event=TriggerEvent.from_journaled(_journaled(data), stream_name="shop orders"),
    )
    assert block.event_file is None
    assert "- Trigger: Orders (stream)" in block.text
    assert "- Stream: shop orders" in block.text
    assert "- Event kind: order.paid" in block.text
    assert "- Event key: webhook-id:evt-1" in block.text
    assert "- Received: 2026-10-06T09:30:15+00:00" in block.text
    assert "- Stream sequence: 7" in block.text
    assert f"```json\n{event_data_json(data)}\n```" in block.text


def test_a_large_event_is_named_as_a_task_file_and_not_quoted():
    data = {"items": ["x" * 1024 for _ in range(40)], "tail": "END-OF-PAYLOAD"}
    block = render_event_block(
        trigger_name="Orders",
        trigger_type="stream",
        event=TriggerEvent.from_journaled(_journaled(data, sequence=42), stream_name="s"),
    )
    assert block.event_file == "trigger-event-42.json"
    assert "`inputs/attachments/trigger-event-42.json`" in block.text
    assert f"{len(event_data_json(data).encode())} bytes" in block.text
    assert "END-OF-PAYLOAD" not in block.text
    assert "- Stream sequence: 42" in block.text


def test_the_inline_limit_is_inclusive_and_one_byte_over_goes_to_a_file():
    data = {"pad": ""}
    data["pad"] = "a" * (EVENT_INLINE_LIMIT_BYTES - len(event_data_json(data).encode()))
    assert len(event_data_json(data).encode()) == EVENT_INLINE_LIMIT_BYTES
    event = TriggerEvent(received_at=RECEIVED, data=data)
    assert render_event_block(trigger_name="t", trigger_type="webhook", event=event).event_file is None

    data["pad"] += "a"
    over = TriggerEvent(received_at=RECEIVED, data=data)
    assert (
        render_event_block(trigger_name="t", trigger_type="webhook", event=over).event_file
        == "trigger-event.json"
    )


def test_nothing_is_cut_the_quoted_data_reads_back_as_the_event():
    data = {"body": "y" * (EVENT_INLINE_LIMIT_BYTES - 200), "nested": {"list": [1, 2, 3]}}
    block = render_event_block(
        trigger_name="t",
        trigger_type="stream",
        event=TriggerEvent(received_at=RECEIVED, data=data),
    )
    quoted = block.text.split("```json\n", 1)[1].rsplit("\n```", 1)[0]
    assert json.loads(quoted) == data


def test_only_the_scrubbed_journal_payload_reaches_the_agent():
    parsed = {
        "webhook_id": "wh",
        "method": "POST",
        "headers": {
            "Authorization": "Bearer sk-live-secret",
            "X-Hub-Signature-256": "sha256=deadbeef",
            "X-GitHub-Event": "pull_request",
        },
        "query_params": {"token": "qs-secret", "page": "2"},
        "raw_data": {"number": 12},
    }
    event = TriggerEvent.from_journaled(_journaled(journal_data(parsed)), stream_name="gh")
    text = render_event_block(trigger_name="t", trigger_type="webhook", event=event).text
    assert "sk-live-secret" not in text
    assert "deadbeef" not in text
    assert "qs-secret" not in text
    assert "pull_request" in text and '"page": "2"' in text


def test_a_naive_received_time_is_read_as_utc():
    event = TriggerEvent(received_at=datetime(2026, 10, 6, 9, 0), data={})
    text = render_event_block(trigger_name="t", trigger_type="cron", event=event).text
    assert "- Received: 2026-10-06T09:00:00+00:00" in text


def test_a_stream_trigger_asks_its_instruction_and_shows_the_order():
    data = {"order": {"id": "A-1003"}}
    task_input = compose_task_input(
        _stream_trigger("Reply naming the order id"),
        data,
        TriggerEvent.from_journaled(_journaled(data), stream_name="orders"),
    )
    assert task_input is not None
    assert task_input.ask == "Reply naming the order id"
    assert task_input.message.startswith("Reply naming the order id\n\n## What started this run")
    assert "A-1003" in task_input.message
    assert task_input.event_file is None
    assert task_input.stamp({}) == {}


def test_a_large_stream_event_stamps_the_file_the_run_must_provision():
    data = {"blob": "z" * (EVENT_INLINE_LIMIT_BYTES + 1)}
    task_input = compose_task_input(
        _stream_trigger("Summarise"),
        data,
        TriggerEvent.from_journaled(_journaled(data, sequence=9), stream_name="orders"),
    )
    assert task_input is not None
    assert task_input.stamp({"trigger_data": data}) == {
        "trigger_data": data,
        "trigger_event_file": "trigger-event-9.json",
    }


def test_a_chat_message_with_no_instruction_is_still_the_ask():
    trigger = WebhookTrigger(
        name="Support bot",
        agent_id=uuid4(),
        created_by="u",
        workspace_id="w",
        webhook_id="wh-1234567890abcd",
        webhook_type="telegram",
    )
    data = {"text": "where is my parcel?", "chat_id": 42, "raw_data": {"update_id": 1}}
    task_input = compose_task_input(
        trigger,
        data,
        TriggerEvent.from_journaled(
            _journaled(data, kind="message", key="telegram:1"), stream_name="tg"
        ),
    )
    assert task_input is not None
    assert task_input.ask == "where is my parcel?"
    assert task_input.message.startswith("where is my parcel?\n\n")
    assert task_input.stamp({})["follow_up_message"] == "where is my parcel?"


def test_a_webhook_texts_never_displaces_the_trigger_instruction():
    trigger = WebhookTrigger(
        name="Incidents",
        agent_id=uuid4(),
        created_by="u",
        workspace_id="w",
        webhook_id="wh-1234567890abcd",
        task_parameters={"text": "Open a ticket for this incident"},
    )
    data = {"body": {"text": "db is down", "severity": "high"}, "text": "db is down"}
    task_input = compose_task_input(
        trigger,
        data,
        TriggerEvent.from_journaled(_journaled(data, kind="webhook.generic"), stream_name="in"),
    )
    assert task_input is not None
    assert task_input.ask == "Open a ticket for this incident"
    assert task_input.message.startswith("Open a ticket for this incident\n\n## What started")
    assert task_input.message.index("Open a ticket") < task_input.message.index("db is down")
    assert task_input.stamp({})["follow_up_message"] == "db is down"


def test_an_event_without_text_stamps_no_follow_up():
    data = {"order": {"id": "A-1"}}
    task_input = compose_task_input(
        _stream_trigger("go"), data, TriggerEvent.from_journaled(_journaled(data), stream_name="s")
    )
    assert task_input is not None
    assert "follow_up_message" not in task_input.stamp({})


def test_an_event_with_nothing_to_ask_starts_nothing():
    data = {"order": {"id": "A-1"}}
    assert (
        compose_task_input(
            _stream_trigger(),
            data,
            TriggerEvent.from_journaled(_journaled(data), stream_name="s"),
        )
        is None
    )


def test_the_event_must_carry_the_data_the_task_stores():
    with pytest.raises(ValueError, match="must carry the trigger data"):
        compose_task_input(
            _stream_trigger("go"),
            {"a": 1},
            TriggerEvent.from_journaled(_journaled({"a": 2}), stream_name="s"),
        )


def test_channel_events_without_a_stream_get_the_same_block():
    data = {"events": [{"text": "hi", "from": "ann"}], "channel_origin": {"chat_id": "c"}}
    task_input = compose_task_input(_stream_trigger(), data)
    assert task_input is not None
    assert task_input.ask == "hi"
    assert "## What started this run" in task_input.message
    assert '"from": "ann"' in task_input.message
    assert "- Stream:" not in task_input.message


def test_a_schedule_tick_carries_no_event_so_the_message_is_the_ask():
    task_input = compose_task_input(_stream_trigger("Score leads"), {"source": "schedule"})
    assert task_input is not None
    assert task_input.message == "Score leads"
