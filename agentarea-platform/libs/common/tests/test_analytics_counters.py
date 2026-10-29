"""Failure counters add up in memory, leave as one ``counters`` event and start over,
and do nothing while analytics is off."""

import json

import httpx
import pytest
from agentarea_common.analytics import AnalyticsSender, count, count_run_refused, runtime
from agentarea_common.analytics.sender import MAX_COUNTER_SERIES
from agentarea_common.config import get_settings


class _Collector:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.events.extend(json.loads(request.content))
        return httpx.Response(202)

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))


@pytest.fixture
def collector(monkeypatch) -> _Collector:
    collector = _Collector()
    sender = AnalyticsSender(enabled=True, install_id="install-1", client_factory=collector.client)
    monkeypatch.setattr(runtime, "_sender", sender)
    return collector


async def _send() -> None:
    sender = runtime.current_sender()
    assert sender is not None
    sender.roll_up_counters()
    await sender.flush()


def _counters(collector: _Collector) -> list[list[dict]]:
    return [event["properties"]["counters"] for event in collector.events]


async def test_counts_add_up_by_name_and_labels_and_leave_as_one_event(collector):
    count("oauth_connect", provider="github", outcome="started")
    count("oauth_connect", outcome="started", provider="github")
    count("oauth_connect", provider="github", outcome="succeeded")
    count("connector_check", kind="mcp", outcome="ok")

    await _send()

    [event] = collector.events
    assert event["event"] == "counters"
    assert sorted(event["properties"]["counters"], key=json.dumps) == sorted(
        [
            {
                "name": "oauth_connect",
                "labels": {"outcome": "started", "provider": "github"},
                "count": 2,
            },
            {
                "name": "oauth_connect",
                "labels": {"outcome": "succeeded", "provider": "github"},
                "count": 1,
            },
            {"name": "connector_check", "labels": {"kind": "mcp", "outcome": "ok"}, "count": 1},
        ],
        key=json.dumps,
    )


async def test_counts_start_over_after_each_send(collector):
    count("run_refused", reason="budget_cap")
    await _send()
    await _send()
    count("run_refused", reason="budget_cap")
    await _send()

    assert (
        _counters(collector)
        == [[{"name": "run_refused", "labels": {"reason": "budget_cap"}, "count": 1}]] * 2
    )


async def test_stop_sends_what_was_counted(collector):
    count("run_refused", reason="budget_cap")

    await runtime.stop_analytics()

    assert _counters(collector) == [
        [{"name": "run_refused", "labels": {"reason": "budget_cap"}, "count": 1}]
    ]


async def test_a_label_that_is_not_enum_like_is_sent_as_other(collector):
    count("oauth_connect", provider="MCP.Example.com", outcome="failed:Access Denied by Bob")
    count("oauth_connect", provider="https://idp.example/tenant/42", outcome="failed:access_denied")

    await _send()

    labels = sorted((c["labels"] for c in _counters(collector)[0]), key=json.dumps)
    assert labels == sorted(
        [
            {"provider": "mcp.example.com", "outcome": "failed:other"},
            {"provider": "https:other", "outcome": "failed:access_denied"},
        ],
        key=json.dumps,
    )


@pytest.mark.parametrize(
    ("code", "reason"),
    [
        ("no_credits", "no_credits"),
        ("credit_limit_reached", "no_credits"),
        (None, "policy_denied"),
        ("model_unpriced", "other"),
        ("duration_required", "other"),
        ("some_future_code", "other"),
    ],
)
async def test_a_refused_run_is_counted_by_why(collector, code, reason):
    count_run_refused(code)

    await _send()

    assert _counters(collector) == [
        [{"name": "run_refused", "labels": {"reason": reason}, "count": 1}]
    ]


async def test_past_the_series_cap_a_counter_folds_into_its_name_under_overflow(collector):
    for n in range(MAX_COUNTER_SERIES + 5):
        count("connector_check", kind="mcp", outcome=f"code{n}")
    count("connector_check", kind="mcp", outcome="code0")
    count("run_refused", reason="budget_cap")

    await _send()

    [counters] = _counters(collector)
    assert len(counters) == MAX_COUNTER_SERIES + 2
    by_labels = {json.dumps([c["name"], c["labels"]], sort_keys=True): c["count"] for c in counters}
    assert by_labels[json.dumps(["connector_check", {"overflow": "true"}])] == 5
    assert by_labels[json.dumps(["run_refused", {"overflow": "true"}])] == 1
    assert (
        by_labels[json.dumps(["connector_check", {"kind": "mcp", "outcome": "code0"}], sort_keys=True)]
        == 2
    )


async def test_the_series_cap_is_per_roll_up(collector):
    for n in range(MAX_COUNTER_SERIES):
        count("connector_check", outcome=f"code{n}")
    await _send()
    count("connector_check", outcome="fresh")

    await _send()

    assert _counters(collector)[1] == [
        {"name": "connector_check", "labels": {"outcome": "fresh"}, "count": 1}
    ]


async def test_a_billing_outage_is_not_a_refusal(collector):
    count_run_refused("billing_unavailable")

    await _send()

    assert collector.events == []


async def test_analytics_off_constructs_no_sender(monkeypatch):
    monkeypatch.setattr(get_settings().analytics, "ENABLED", False)
    monkeypatch.setattr(runtime, "_sender", None)

    def no_session():
        raise AssertionError("analytics off opens no session")

    assert await runtime.start_analytics(no_session) is None  # type: ignore[arg-type]
    assert runtime.current_sender() is None


async def test_analytics_that_cannot_start_is_off_and_never_fails_the_process(
    monkeypatch, caplog
):
    monkeypatch.setattr(get_settings().analytics, "ENABLED", True)
    monkeypatch.setattr(runtime, "_sender", None)

    def unreachable_database():
        raise ConnectionError("database is down")

    assert await runtime.start_analytics(unreachable_database) is None  # type: ignore[arg-type]
    assert runtime.current_sender() is None
    [record] = caplog.records
    assert (record.levelname, record.exc_info is not None) == ("ERROR", True)


def test_counting_with_analytics_off_does_nothing(monkeypatch):
    monkeypatch.setattr(runtime, "_sender", None)

    count("run_refused", reason="budget_cap")
    count_run_refused("no_credits")


async def test_a_disabled_sender_counts_nothing():
    collector = _Collector()
    sender = AnalyticsSender(enabled=False, install_id=None, client_factory=collector.client)
    sender.count("run_refused", {"reason": "budget_cap"})

    await sender.stop()

    assert collector.events == []


def test_a_counter_that_fails_never_reaches_the_caller(monkeypatch, caplog):
    class _Broken:
        def count(self, name, labels):
            raise RuntimeError("boom")

    monkeypatch.setattr(runtime, "_sender", _Broken())

    count("run_refused", reason="budget_cap")

    [record] = caplog.records
    assert record.exc_info is not None
