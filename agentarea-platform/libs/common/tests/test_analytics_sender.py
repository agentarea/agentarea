"""The sender batches events to the collector, drops a batch it cannot send, and is
silent when analytics is off."""

import json
import logging
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from agentarea_common import __version__
from agentarea_common.analytics import COLLECTOR_KEY, COLLECTOR_URL, AnalyticsSender
from agentarea_common.config import get_app_settings


class _Collector:
    def __init__(self, status: int = 202, error: Exception | None = None):
        self.status = status
        self.error = error
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return httpx.Response(self.status)

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))

    def batches(self) -> list[list[dict]]:
        return [json.loads(request.content) for request in self.requests]


def _sender(collector: _Collector, *, enabled: bool = True) -> AnalyticsSender:
    return AnalyticsSender(
        enabled=enabled,
        install_id="install-1" if enabled else None,
        client_factory=collector.client,
    )


async def test_events_are_posted_in_batches_of_at_most_500():
    collector = _Collector()
    sender = _sender(collector)
    for n in range(1201):
        sender.enqueue({"event": "counters", "properties": {"n": n}})

    sent = await sender.flush()

    assert sent == 1201
    assert [len(batch) for batch in collector.batches()] == [500, 500, 201]
    request = collector.requests[0]
    assert str(request.url) == f"{COLLECTOR_URL}/v1/events"
    assert request.headers["Authorization"] == f"Bearer {COLLECTOR_KEY}"


async def test_every_event_carries_the_installation_context():
    collector = _Collector()
    sender = _sender(collector)
    sender.enqueue({"event": "installation_pulse", "properties": {"agents": 3}})

    await sender.flush()

    [[event]] = collector.batches()
    assert event["event"] == "installation_pulse"
    assert event["properties"] == {"agents": 3}
    assert event["context"] == {
        "install_id": "install-1",
        "version": __version__,
        "edition": get_app_settings().EDITION,
    }
    assert event["occurred_at"].endswith("+00:00")


async def test_a_flush_with_nothing_queued_sends_nothing():
    collector = _Collector()

    assert await _sender(collector).flush() == 0
    assert collector.requests == []


@pytest.mark.parametrize(
    "collector",
    [_Collector(status=500), _Collector(error=httpx.ConnectError("collector unreachable"))],
    ids=["rejected", "unreachable"],
)
async def test_a_batch_that_fails_is_logged_and_dropped(collector, caplog):
    sender = _sender(collector)
    sender.enqueue({"event": "counters"})

    with caplog.at_level(logging.WARNING, logger="agentarea_common.analytics.sender"):
        assert await sender.flush() == 0

    [record] = caplog.records
    assert record.exc_info is not None
    assert await sender.flush() == 0
    assert len(collector.requests) == 1


class _Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 14, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


async def test_an_outage_is_logged_once_then_daily_then_once_on_recovery(caplog):
    collector = _Collector(status=503)
    clock = _Clock()
    sender = AnalyticsSender(
        enabled=True, install_id="install-1", client_factory=collector.client, clock=clock
    )

    async def flush(n: int, after: timedelta) -> None:
        clock.now += after
        for _ in range(n):
            sender.enqueue({"event": "counters"})
        await sender.flush()

    with caplog.at_level(logging.INFO, logger="agentarea_common.analytics.sender"):
        await flush(1, timedelta(0))
        for _ in range(23):
            await flush(2, timedelta(hours=1))
        await flush(3, timedelta(hours=1))
        await flush(1, timedelta(hours=1))
        collector.status = 202
        await flush(1, timedelta(hours=1))
        await flush(1, timedelta(hours=1))

    first, daily, recovered = caplog.records
    assert (first.levelno, first.exc_info is not None) == (logging.WARNING, True)
    assert (daily.levelno, daily.exc_info) == (logging.WARNING, None)
    assert "dropped 49 since" in daily.getMessage()
    assert (recovered.levelno, recovered.exc_info) == (logging.INFO, None)
    assert "51 were dropped" in recovered.getMessage()


async def test_a_new_outage_after_recovery_is_logged_with_its_traceback(caplog):
    collector = _Collector(status=503)
    sender = _sender(collector)

    with caplog.at_level(logging.WARNING, logger="agentarea_common.analytics.sender"):
        for status in (503, 202, 503):
            collector.status = status
            sender.enqueue({"event": "counters"})
            await sender.flush()

    assert [record.exc_info is not None for record in caplog.records] == [True, True]


async def test_nothing_is_queued_or_sent_when_analytics_is_off():
    collector = _Collector()
    sender = _sender(collector, enabled=False)
    sender.enqueue({"event": "counters"})

    await sender.start()
    await sender.stop()

    assert await sender.flush() == 0
    assert collector.requests == []


async def test_stop_sends_what_is_still_queued():
    collector = _Collector()
    sender = _sender(collector)
    await sender.start()
    sender.enqueue({"event": "counters"})

    await sender.stop()

    assert [len(batch) for batch in collector.batches()] == [1]


def test_an_enabled_sender_needs_an_installation():
    with pytest.raises(ValueError, match="install_id"):
        AnalyticsSender(enabled=True, install_id=None)
