"""A call to an MCP instance is stamped on the instance, off the call path."""

import asyncio
import logging
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from agentarea_mcp import dispatch_stamps
from agentarea_mcp.application import mcp_aggregator
from agentarea_mcp.application.mcp_aggregator import AggregatedMember, MCPAggregatorProxy
from agentarea_mcp.dispatch_stamps import DispatchStampWriter, record_dispatch
from mcp.types import CallToolResult, TextContent


class _Session:
    def __init__(self, writes: list[dict], fail: bool = False) -> None:
        self._writes = writes
        self._fail = fail
        self._pending: list[dict] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, statement):
        if self._fail:
            raise RuntimeError("database is gone")
        params = statement.compile().params
        self._pending.append({"id": params["id_1"], "last_dispatch": params["last_dispatch"]})

    async def commit(self):
        self._writes.extend(self._pending)


@pytest.fixture(autouse=True)
def pending(monkeypatch):
    queue: asyncio.Queue = asyncio.Queue(maxsize=3)
    monkeypatch.setattr(dispatch_stamps, "_pending", queue)
    return queue


@pytest.fixture
def writes() -> list[dict]:
    return []


@pytest.fixture
def writer(writes) -> DispatchStampWriter:
    return DispatchStampWriter(lambda: _Session(writes), interval=0.01)


async def _until(predicate, timeout: float = 2.0) -> None:
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.01)


async def test_a_running_writer_stamps_each_call_on_its_instance(writer, writes):
    ok, broken = uuid4(), uuid4()
    await writer.start()
    try:
        record_dispatch(ok)
        record_dispatch(str(broken), error="401 Unauthorized")
        await _until(lambda: len(writes) == 2)
    finally:
        await writer.stop()

    stamps = {w["id"]: w["last_dispatch"] for w in writes}
    assert stamps[ok]["status"] == "succeeded"
    assert stamps[ok]["error"] is None
    assert stamps[broken]["status"] == "failed"
    assert stamps[broken]["error"] == "401 Unauthorized"
    assert stamps[ok]["at"]


async def test_the_latest_call_wins_within_one_batch(writer, writes):
    instance = uuid4()
    record_dispatch(instance, error="timed out")
    record_dispatch(instance)

    await writer.flush()

    assert [w["last_dispatch"]["status"] for w in writes] == ["succeeded"]


async def test_stopping_writes_what_was_queued(writes):
    writer = DispatchStampWriter(lambda: _Session(writes), interval=3600)
    instance = uuid4()
    await writer.start()
    record_dispatch(instance)

    await writer.stop()

    assert [w["id"] for w in writes] == [instance]


def test_a_full_queue_drops_the_stamp_without_blocking_the_call(pending, monkeypatch):
    dropped = SimpleNamespace(count=0)
    monkeypatch.setattr(
        dispatch_stamps._dropped_total, "inc", lambda: setattr(dropped, "count", dropped.count + 1)
    )
    for _ in range(4):
        record_dispatch(uuid4())

    assert pending.qsize() == 3
    assert dropped.count == 1


async def test_a_failed_write_is_logged_and_the_writer_keeps_going(writes, caplog):
    caplog.set_level(logging.ERROR, logger="agentarea_mcp.dispatch_stamps")
    sessions = iter([_Session(writes, fail=True), _Session(writes)])
    writer = DispatchStampWriter(lambda: next(sessions), interval=0.01)
    first, second = uuid4(), uuid4()
    record_dispatch(first)
    await writer.start()
    try:
        await _until(lambda: dispatch_stamps._pending.empty())
        record_dispatch(second)
        await _until(lambda: len(writes) == 1)
    finally:
        await writer.stop()

    assert [w["id"] for w in writes] == [second]
    [failure] = caplog.records
    assert failure.getMessage() == "Writing 1 MCP dispatch stamps failed"
    assert failure.exc_info is not None


def _proxy(instance_id) -> MCPAggregatorProxy:
    return MCPAggregatorProxy(
        "gw",
        "",
        [AggregatedMember(mcp_instance_id=instance_id)],
        {str(instance_id): "https://mcp.example.com/mcp"},
        {str(instance_id): "ga"},
    )


def _upstream(monkeypatch, call_tool):
    @asynccontextmanager
    async def connected(*_args, **_kwargs):
        yield SimpleNamespace(call_tool=call_tool)

    monkeypatch.setattr(mcp_aggregator, "connected_mcp_client", connected)


async def _queued() -> list:
    items = []
    while not dispatch_stamps._pending.empty():
        items.append(dispatch_stamps._pending.get_nowait())
    return items


async def test_a_gateway_call_stamps_its_instance(monkeypatch):
    instance = uuid4()

    async def call_tool(name, arguments):
        return CallToolResult(content=[TextContent(type="text", text="rows")])

    _upstream(monkeypatch, call_tool)

    await _proxy(instance).call_namespaced_tool_result("ga__run_report", {})

    [(stamped, stamp)] = await _queued()
    assert stamped == str(instance)
    assert stamp["status"] == "succeeded"


async def test_a_gateway_call_the_upstream_refuses_stamps_a_failure(monkeypatch):
    instance = uuid4()

    async def call_tool(name, arguments):
        return CallToolResult(content=[TextContent(type="text", text="quota exceeded")], is_error=True)

    _upstream(monkeypatch, call_tool)

    await _proxy(instance).call_namespaced_tool_result("ga__run_report", {})

    [(_, stamp)] = await _queued()
    assert stamp["status"] == "failed"
    assert stamp["error"] == "quota exceeded"


async def test_a_gateway_call_that_cannot_reach_the_upstream_stamps_a_failure(monkeypatch):
    instance = uuid4()

    async def call_tool(name, arguments):
        raise ConnectionError("connection refused")

    _upstream(monkeypatch, call_tool)

    with pytest.raises(ConnectionError):
        await _proxy(instance).call_namespaced_tool_result("ga__run_report", {})

    [(_, stamp)] = await _queued()
    assert stamp["status"] == "failed"
    assert stamp["error"] == "connection refused"


async def test_a_malformed_instance_id_never_fails_the_call_and_is_not_written(writer, writes):
    record_dispatch("not-a-uuid")
    good = uuid4()
    record_dispatch(good)

    await writer.flush()

    assert [w["id"] for w in writes] == [good]
