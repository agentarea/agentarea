from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from agentarea_worker.streams import StreamRuntime, build_stream_runtime


async def test_partitions_exist_before_the_groups_consume_and_they_stop_first():
    order: list[str] = []
    router, events_view, changes, partitions = MagicMock(), MagicMock(), MagicMock(), MagicMock()
    bus = MagicMock()
    partitions.start = AsyncMock(side_effect=lambda: order.append("partitions"))
    changes.start = AsyncMock(side_effect=lambda on_change: order.append("changes"))

    def subscribed(**kwargs):
        order.append(kwargs["group"])
        subscription = MagicMock()
        subscription.stop = AsyncMock(side_effect=lambda: order.append(f"stop {kwargs['group']}"))
        return subscription

    bus.events.subscribe_many = AsyncMock(side_effect=subscribed)
    changes.stop = AsyncMock(side_effect=lambda: order.append("stop changes"))
    partitions.stop = AsyncMock(side_effect=lambda: order.append("stop partitions"))
    bus.aclose = AsyncMock(side_effect=lambda: order.append("close bus"))
    polled, autoclaimer = MagicMock(), MagicMock()
    polled.start = AsyncMock(side_effect=lambda: order.append("polled"))
    polled.stop = AsyncMock(side_effect=lambda: order.append("stop polled"))
    autoclaimer.start = AsyncMock(side_effect=lambda: order.append("autoclaimer"))
    autoclaimer.stop = AsyncMock(side_effect=lambda: order.append("stop autoclaimer"))

    topics = ["streams.events.0", "streams.events.1"]
    runtime = StreamRuntime(
        router=router,
        events_view=events_view,
        changes=changes,
        partitions=partitions,
        bus=bus,
        topics=topics,
        polled=polled,
        polled_autoclaimer=autoclaimer,
    )
    await runtime.start()
    await runtime.stop()

    assert order == [
        "partitions",
        "polled",
        "autoclaimer",
        "changes",
        "events-view",
        "router",
        "stop autoclaimer",
        "stop polled",
        "stop events-view",
        "stop router",
        "stop changes",
        "stop partitions",
        "close bus",
    ]
    changes.start.assert_awaited_once_with(router.invalidate)
    calls = {c.kwargs["group"]: c.kwargs for c in bus.events.subscribe_many.await_args_list}
    assert calls["router"]["topics"] == topics
    assert calls["events-view"]["topics"] == topics
    assert calls["router"]["handler"] == router.handle
    assert calls["router"]["dead_letter_topic"] == "streams.events.router.dlq"
    assert calls["events-view"]["dead_letter_topic"] == "streams.events.events-view.dlq"
    assert calls["router"]["on_dead_letter"] == router.give_up
    assert calls["events-view"]["handler"] == events_view.handle


def test_the_runtime_refuses_to_build_without_a_workflow_executor():
    dependencies = SimpleNamespace(
        event_broker=MagicMock(), secret_manager_factory=MagicMock(), workflow_executor=None
    )
    with pytest.raises(RuntimeError, match="workflow executor"):
        build_stream_runtime(MagicMock(), dependencies)
