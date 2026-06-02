import json
from unittest.mock import AsyncMock

import pytest
from agentarea_common.broker import BrokerMessage
from agentarea_triggers.channels.inbound_subscriber import InboundMessageStreamConsumer


class FakeBroker:
    def __init__(self):
        self.acked: list[tuple[str, str, str]] = []
        self.submitted: list[tuple[str, dict[str, str]]] = []

    async def ensure_group(self, stream: str, group: str, start: str = "$") -> None:
        pass

    async def consume(self, *args, **kwargs):
        return []

    async def ack(self, stream: str, group: str, message_id: str) -> None:
        self.acked.append((stream, group, message_id))

    async def submit(self, stream: str, fields: dict[str, str]) -> str:
        self.submitted.append((stream, fields))
        return "dlq-id"


class FakeDedup:
    def __init__(self, claimed: bool = True):
        self.claimed = claimed
        self.claim_calls: list[str] = []
        self.release_calls: list[str] = []

    async def claim(self, key: str) -> bool:
        self.claim_calls.append(key)
        return self.claimed

    async def release(self, key: str) -> None:
        self.release_calls.append(key)


class InboundConsumerHarness(InboundMessageStreamConsumer):
    def __init__(self, broker, dedup):
        super().__init__(
            broker,
            dedup,
            event_broker=AsyncMock(),
            stream="inbound",
            group="workers",
            dlq_stream="inbound.dlq",
        )
        self.executed: list[tuple[str, dict]] = []
        self.fail_execute = False

    async def _execute_trigger(self, trigger_id: str, trigger_data: dict) -> None:
        self.executed.append((trigger_id, trigger_data))
        if self.fail_execute:
            raise RuntimeError("boom")


@pytest.mark.asyncio
async def test_inbound_stream_message_executes_and_acks():
    broker = FakeBroker()
    dedup = FakeDedup()
    consumer = InboundConsumerHarness(broker, dedup)
    msg = BrokerMessage(
        id="1-0",
        fields={
            "trigger_id": "trigger-1",
            "event": json.dumps({"type": "message", "text": "hello"}),
            "channel_origin": json.dumps({"type": "telegram", "chat_id": "42"}),
            "dedup_key": "tg:42:7",
        },
    )

    await consumer._handle(msg)

    assert consumer.executed == [
        (
            "trigger-1",
            {
                "events": [{"type": "message", "text": "hello"}],
                "channel_origin": {"type": "telegram", "chat_id": "42"},
            },
        )
    ]
    assert broker.acked == [("inbound", "workers", "1-0")]
    assert broker.submitted == []


@pytest.mark.asyncio
async def test_inbound_stream_malformed_message_goes_to_dlq():
    broker = FakeBroker()
    dedup = FakeDedup()
    consumer = InboundConsumerHarness(broker, dedup)
    msg = BrokerMessage(
        id="1-0",
        fields={
            "trigger_id": "trigger-1",
            "event": "{bad",
            "channel_origin": "{}",
            "dedup_key": "bad",
        },
    )

    await consumer._handle(msg)

    assert consumer.executed == []
    assert broker.acked == [("inbound", "workers", "1-0")]
    assert broker.submitted[0][0] == "inbound.dlq"
    assert "fatal_reason" in broker.submitted[0][1]


@pytest.mark.asyncio
async def test_inbound_stream_execution_failure_releases_dedup_without_ack():
    broker = FakeBroker()
    dedup = FakeDedup()
    consumer = InboundConsumerHarness(broker, dedup)
    consumer.fail_execute = True
    msg = BrokerMessage(
        id="1-0",
        fields={
            "trigger_id": "trigger-1",
            "event": json.dumps({"type": "message"}),
            "channel_origin": json.dumps({}),
            "dedup_key": "retry-me",
        },
    )

    await consumer._handle(msg)

    assert broker.acked == []
    assert broker.submitted == []
    assert dedup.release_calls == ["retry-me"]
