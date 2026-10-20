"""A consumer group the broker lost with its data is recreated on the next read.

Runs without Redis: the client below answers the way Redis does once a restart
without persistence wiped the stream keys and their groups (the error texts are
Redis's own). The same behaviour against a live Redis is covered in
test_broker_redis_streams.py.
"""

from __future__ import annotations

from typing import Any

import pytest
from agentarea_common.broker import RedisStreamsBroker
from redis.exceptions import ResponseError

pytestmark = pytest.mark.asyncio


class _WipedRedis:
    def __init__(self) -> None:
        self.groups: dict[tuple[str, str], str] = {}
        self.reads = 0

    async def xgroup_create(self, name: str, groupname: str, id: str, mkstream: bool) -> None:
        assert mkstream
        if (name, groupname) in self.groups:
            raise ResponseError("BUSYGROUP Consumer Group name already exists")
        self.groups[(name, groupname)] = id

    async def xreadgroup(
        self, groupname: str, consumername: str, streams: dict[str, str], count: int, block: int
    ) -> Any:
        self.reads += 1
        for key in streams:
            if (key, groupname) not in self.groups:
                raise ResponseError(
                    f"NOGROUP No such key '{key}' or consumer group '{groupname}' "
                    + "in XREADGROUP with GROUP option"
                )
        return []

    async def xautoclaim(self, name: str, groupname: str, **_: Any) -> Any:
        if (name, groupname) not in self.groups:
            raise ResponseError(f"NOGROUP No such key '{name}' or consumer group '{groupname}'")
        return ["0-0", [], []]

    async def eval(self, *_: Any) -> int:
        return 0


def _broker(client: _WipedRedis) -> RedisStreamsBroker:
    broker = RedisStreamsBroker("redis://unused", namespace="ns")
    broker._client = client  # pyright: ignore[reportAttributeAccessIssue]
    return broker


async def test_a_read_recreates_the_lost_group_from_the_start_and_reads_again(
    caplog: pytest.LogCaptureFixture,
):
    client = _WipedRedis()

    with caplog.at_level("WARNING"):
        assert await _broker(client).consume("s", "g", "c") == []

    assert client.groups == {("ns.s", "g"): "0"}
    assert client.reads == 2
    warning = next(r for r in caplog.records if r.levelname == "WARNING")
    assert warning.exc_info is not None


async def test_a_read_over_many_streams_recreates_the_group_on_each():
    client = _WipedRedis()
    client.groups[("ns.a", "g")] = "$"

    assert await _broker(client).consume_many(["a", "b"], "g", "c") == []

    assert client.groups == {("ns.a", "g"): "$", ("ns.b", "g"): "0"}
    assert client.reads == 2


async def test_a_reclaim_recreates_the_lost_group_and_has_nothing_to_reclaim():
    client = _WipedRedis()

    assert await _broker(client).autoclaim("s", "g", "c", min_idle_ms=10) == []

    assert client.groups == {("ns.s", "g"): "0"}


async def test_a_group_lost_again_on_the_second_read_is_left_to_the_caller():
    class _LosesEveryGroup(_WipedRedis):
        async def xgroup_create(self, name: str, groupname: str, id: str, mkstream: bool) -> None:
            return None

    client = _LosesEveryGroup()

    with pytest.raises(ResponseError, match="NOGROUP"):
        await _broker(client).consume("s", "g", "c")
    assert client.reads == 2


async def test_other_read_errors_are_not_taken_for_a_lost_group():
    class _Broken(_WipedRedis):
        async def xreadgroup(self, *_: Any, **__: Any) -> Any:
            self.reads += 1
            raise ResponseError("WRONGTYPE Operation against a key holding the wrong kind of value")

    client = _Broken()

    with pytest.raises(ResponseError, match="WRONGTYPE"):
        await _broker(client).consume("s", "g", "c")
    assert client.groups == {}
    assert client.reads == 1
