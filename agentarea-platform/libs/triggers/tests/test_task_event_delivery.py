"""The ``delivery`` group on ``tasks.events``: each task event to where its task replies.

A delivered target is marked only after its send succeeded, so a send that never
finished (a failure, a shutdown, a crash) is sent again; a fatal failure or the
attempt cap dead-letters that target alone, naming it, and a replay of the dead
letter sends there only.
"""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from agentarea_common.broker import BrokerMessage
from agentarea_common.broker.dlq import DEAD_LETTER_REASON_FIELD
from agentarea_common.events.adapters.redis_streams import encode
from agentarea_common.events.task_stream import task_event
from agentarea_common.testing.flows import MainFlow
from agentarea_streams.domain.source_types import Reply
from agentarea_triggers.channels.exceptions import FatalError, RetryableError
from agentarea_triggers.channels.task_delivery import (
    DELIVERY_DLQ,
    DELIVERY_TARGET_FIELD,
    TaskEventDelivery,
    delivery_targets,
)

TASK_ID = uuid4()
WORKSPACE = "ws-1"


class _Broker:
    def __init__(self) -> None:
        self.acked: list[str] = []
        self.dead: list[dict[str, str]] = []

    async def ack(self, stream, group, message_id):
        self.acked.append(message_id)

    async def submit(self, stream, fields, *, retention):
        assert stream == DELIVERY_DLQ
        self.dead.append(dict(fields))
        return "dlq-1"


class _Dedup:
    def __init__(self) -> None:
        self.keys: set[str] = set()

    async def contains(self, key):
        return key in self.keys

    async def claim(self, key, *, hold_seconds=None):
        if key in self.keys:
            return False
        self.keys.add(key)
        return True

    async def release(self, key):
        self.keys.discard(key)


class _Adapter:
    def __init__(self, failure: Exception | None = None) -> None:
        self.failure = failure
        self.sent: list[tuple[dict, str]] = []

    def format(self, event, presentation, config):
        return f"{event['event_type']}:{event['data'].get('final_response', '')}"

    async def send(self, config, message):
        if self.failure is not None:
            raise self.failure
        self.sent.append((config, message))


def _task(**parameters):
    metadata = parameters.pop("metadata", {})
    return SimpleNamespace(parameters=parameters, metadata=metadata, owner="owner-1")


TELEGRAM = {
    "type": "chat_source",
    "sender": "telegram_live",
    "credential_type": "chat_source",
    "credential_key": str(uuid4()),
    "target": {"chat_id": 42},
    "presentation": "concise",
}
REPLY = Reply(sender="telegram_live", target={"chat_id": "{body:chat.id}"}, markup="telegram")


def _message(event_type="task.completed", *, message_id="1-0", count=1, **fields):
    event = task_event(
        task_id=str(TASK_ID),
        workspace_id=WORKSPACE,
        event_type=event_type,
        event_id=str(uuid4()),
        timestamp=datetime.now(UTC),
        data={"final_response": "PONG"},
        seq=7,
    )
    return BrokerMessage(id=message_id, fields={**encode(event), **fields}, delivery_count=count)


def _delivery(task, adapters, *, broker=None, dedup=None, reply=REPLY, max_attempts=20):
    async def load_task(task_id, workspace_id):
        assert (task_id, workspace_id) == (TASK_ID, WORKSPACE)
        return task

    async def reply_for(slug):
        assert slug == TELEGRAM["type"]
        return reply

    return TaskEventDelivery(
        broker or _Broker(),
        dedup or _Dedup(),
        adapters.get,
        load_task=load_task,
        reply_for=reply_for,
        consumer_id="c1",
        max_delivery_attempts=max_attempts,
    )


@pytest.mark.flow(MainFlow.CHANNELS)
async def test_an_event_goes_to_the_tasks_channel_once_and_is_acknowledged():
    adapter, broker, dedup = _Adapter(), _Broker(), _Dedup()
    delivery = _delivery(
        _task(delivery_address=TELEGRAM), {"telegram_live": adapter}, broker=broker, dedup=dedup
    )
    message = _message()

    await delivery.handle(message)
    await delivery.handle(message)

    assert len(adapter.sent) == 1
    config, text = adapter.sent[0]
    assert (config["target"], config["task_id"], config["event_type"]) == (
        {"chat_id": 42},
        str(TASK_ID),
        "task.completed",
    )
    assert (config["workspace_id"], config["owner"]) == (WORKSPACE, "owner-1")
    assert config["reply"] is REPLY
    assert text == "task.completed:PONG"
    assert broker.acked == ["1-0", "1-0"]


async def test_an_event_the_presentation_hides_is_acknowledged_without_sending():
    adapter, broker = _Adapter(), _Broker()
    delivery = _delivery(
        _task(delivery_address=TELEGRAM), {"telegram_live": adapter}, broker=broker
    )
    await delivery.handle(_message("llm.call.completed"))
    assert adapter.sent == []
    assert broker.acked == ["1-0"]


async def test_a_failed_send_is_not_marked_so_the_redelivery_sends_it():
    adapter, broker, dedup = _Adapter(RetryableError("429")), _Broker(), _Dedup()
    delivery = _delivery(
        _task(delivery_address=TELEGRAM), {"telegram_live": adapter}, broker=broker, dedup=dedup
    )
    message = _message()

    await delivery.handle(message)
    assert broker.acked == [] and dedup.keys == set()

    adapter.failure = None
    await delivery.handle(message)
    assert len(adapter.sent) == 1
    assert broker.acked == ["1-0"]


async def test_a_send_cancelled_by_shutdown_leaves_nothing_marked():
    started = asyncio.Event()

    class _Slow(_Adapter):
        async def send(self, config, message):
            started.set()
            await asyncio.sleep(60)

    broker, dedup = _Broker(), _Dedup()
    delivery = _delivery(
        _task(delivery_address=TELEGRAM), {"telegram_live": _Slow()}, broker=broker, dedup=dedup
    )
    handling = asyncio.create_task(delivery.handle(_message()))
    await started.wait()
    handling.cancel()
    with pytest.raises(asyncio.CancelledError):
        await handling

    assert dedup.keys == set()
    assert broker.acked == []


async def test_a_fatal_failure_dead_letters_that_target_only():
    telegram, webhook = _Adapter(FatalError("400 bad chat")), _Adapter()
    broker, dedup = _Broker(), _Dedup()
    task = _task(delivery_address=TELEGRAM, metadata={"task_webhook": {"url": "https://h/x"}})
    delivery = _delivery(
        task, {"telegram_live": telegram, "task_webhook": webhook}, broker=broker, dedup=dedup
    )

    await delivery.handle(_message())

    assert len(webhook.sent) == 1
    (letter,) = broker.dead
    assert letter[DELIVERY_TARGET_FIELD] == "address"
    assert "400 bad chat" in letter[DEAD_LETTER_REASON_FIELD]
    assert broker.acked == ["1-0"]
    assert not any(key.endswith(":address") and not key.startswith("dead:") for key in dedup.keys)


async def test_a_redelivery_does_not_dead_letter_a_target_twice():
    telegram, webhook = _Adapter(FatalError("400")), _Adapter(RetryableError("503"))
    broker = _Broker()
    task = _task(delivery_address=TELEGRAM, metadata={"task_webhook": {"url": "https://h/x"}})
    delivery = _delivery(task, {"telegram_live": telegram, "task_webhook": webhook}, broker=broker)
    message = _message()

    await delivery.handle(message)
    await delivery.handle(message)

    assert len(broker.dead) == 1
    assert broker.acked == []


async def test_past_the_attempt_cap_every_open_target_is_dead_lettered():
    adapter, broker = _Adapter(RetryableError("down")), _Broker()
    delivery = _delivery(
        _task(delivery_address=TELEGRAM), {"telegram_live": adapter}, broker=broker, max_attempts=3
    )
    await delivery.handle(_message(count=4))
    assert adapter.sent == []
    assert "max delivery attempts (3)" in broker.dead[0][DEAD_LETTER_REASON_FIELD]
    assert broker.acked == ["1-0"]


async def test_a_replayed_dead_letter_goes_to_its_target_only():
    telegram, webhook = _Adapter(), _Adapter()
    dedup = _Dedup()
    task = _task(delivery_address=TELEGRAM, metadata={"task_webhook": {"url": "https://h/x"}})
    delivery = _delivery(task, {"telegram_live": telegram, "task_webhook": webhook}, dedup=dedup)
    message = _message(**{DELIVERY_TARGET_FIELD: "address"})
    dedup.keys.add(f"dead:{message.fields['ce_id']}:address")

    await delivery.handle(message)

    assert len(telegram.sent) == 1
    assert webhook.sent == []


async def test_a_channel_with_no_adapter_on_this_worker_stays_pending():
    broker = _Broker()
    delivery = _delivery(_task(delivery_address=TELEGRAM), {}, broker=broker)
    await delivery.handle(_message())
    assert broker.acked == []
    assert broker.dead == []


async def test_an_address_whose_catalog_entry_has_no_reply_is_dead_lettered():
    adapter, broker = _Adapter(), _Broker()
    delivery = _delivery(
        _task(delivery_address=TELEGRAM), {"telegram_live": adapter}, broker=broker, reply=None
    )
    await delivery.handle(_message())
    assert adapter.sent == []
    assert "no reply block" in broker.dead[0][DEAD_LETTER_REASON_FIELD]
    assert broker.acked == ["1-0"]


async def test_an_address_is_sent_by_its_sender_not_its_source_type():
    adapter = _Adapter()
    adapters = {"chat_source": _Adapter(), "telegram_live": adapter}
    delivery = _delivery(_task(delivery_address=TELEGRAM), adapters)
    await delivery.handle(_message())
    assert len(adapter.sent) == 1


async def test_an_event_of_a_deleted_task_is_acknowledged():
    broker = _Broker()
    delivery = _delivery(None, {}, broker=broker)
    await delivery.handle(_message())
    assert broker.acked == ["1-0"]


async def test_targets_come_from_the_task_address_webhook_and_push_configs():
    task = _task(
        delivery_address=TELEGRAM,
        a2a_push_configs=[{"id": "p1", "url": "https://a/1"}, {"url": "no-id"}],
        metadata={
            "task_webhook": {"url": "https://h/x", "signed": True},
            "end_user_id": "u-1",
        },
    )
    targets = {t.key: t for t in delivery_targets(task)}
    assert set(targets) == {"address", "task_webhook", "a2a:p1"}
    assert targets["address"].channel_type == "telegram_live"
    assert targets["task_webhook"].config["signed"] is True
    assert targets["task_webhook"].data["end_user_id"] == "u-1"
    assert targets["a2a:p1"].config["url"] == "https://a/1"


async def test_an_email_reply_carries_the_answer_to_the_one_sender():
    from agentarea_triggers.channels.email import EmailAdapter

    read = []

    async def credentials(**kwargs):
        read.append(kwargs)
        return {"smtp_host": "smtp.example.com", "from_address": "a@x.io"}

    adapter = EmailAdapter(credentials, connect=AsyncMock(return_value=MagicMock()))
    address = {
        "type": "mailbox",
        "sender": "smtp",
        "credential_type": "mailbox",
        "credential_key": "key-1",
        "target": {
            "to": "One <one@example.com>, two@example.com",
            "subject": "inject\r\nBcc: evil@evil.test",
            "message_id": "<m1@example.com>",
            "references": ["<root@example.com>"],
        },
        "presentation": "summary",
    }
    mail_reply = Reply(sender="smtp", presentation="summary")

    async def load_task(task_id, workspace_id):
        return _task(delivery_address=address)

    async def reply_for(slug):
        return mail_reply

    delivery = TaskEventDelivery(
        _Broker(),
        _Dedup(),
        {"smtp": adapter}.get,
        load_task=load_task,
        reply_for=reply_for,
        consumer_id="c1",
    )

    with patch("agentarea_triggers.channels.email.aiosmtplib.send", new=AsyncMock()) as send:
        await delivery.handle(_message("task.started"))
        await delivery.handle(_message("task.completed", message_id="2-0"))

    send.assert_awaited_once()
    sent = send.await_args.args[0]
    assert sent["To"] == "one@example.com"
    assert sent["Subject"] == "Re: inject Bcc: evil@evil.test"
    assert sent["References"] == "<root@example.com> <m1@example.com>"
    assert "PONG" in sent.get_payload()[0].get_payload()
    assert read == [
        {
            "workspace_id": WORKSPACE,
            "owner": "owner-1",
            "credential_type": "mailbox",
            "credential_key": "key-1",
        }
    ]
