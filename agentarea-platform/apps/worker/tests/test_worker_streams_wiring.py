from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from agentarea_worker.streams import StreamRuntime, build_stream_runtime


async def test_partitions_exist_before_the_dispatcher_starts_and_it_stops_first():
    order: list[str] = []
    dispatcher, listener, partitions, waker = MagicMock(), MagicMock(), MagicMock(), MagicMock()
    partitions.start = AsyncMock(side_effect=lambda: order.append("partitions"))
    listener.start = AsyncMock(side_effect=lambda notify: order.append("listener"))
    dispatcher.start = AsyncMock(side_effect=lambda: order.append("dispatcher"))
    dispatcher.stop = AsyncMock(side_effect=lambda: order.append("stop dispatcher"))
    listener.stop = AsyncMock(side_effect=lambda: order.append("stop listener"))
    partitions.stop = AsyncMock(side_effect=lambda: order.append("stop partitions"))
    waker.aclose = AsyncMock(side_effect=lambda: order.append("close waker"))

    runtime = StreamRuntime(
        dispatcher=dispatcher, listener=listener, partitions=partitions, waker=waker
    )
    await runtime.start()
    await runtime.stop()

    assert order == [
        "partitions",
        "listener",
        "dispatcher",
        "stop dispatcher",
        "stop listener",
        "stop partitions",
        "close waker",
    ]
    listener.start.assert_awaited_once_with(dispatcher.notify)


def test_the_runtime_refuses_to_build_without_a_workflow_executor():
    dependencies = SimpleNamespace(
        event_broker=MagicMock(), secret_manager_factory=MagicMock(), workflow_executor=None
    )
    with pytest.raises(RuntimeError, match="workflow executor"):
        build_stream_runtime(MagicMock(), dependencies)
