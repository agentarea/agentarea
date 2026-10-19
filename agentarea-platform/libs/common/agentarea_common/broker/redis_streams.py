"""Redis Streams implementation of `BrokerClient`."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Mapping
from datetime import timedelta
from typing import Any, cast

import redis.asyncio as redis
from redis.exceptions import ResponseError

from .interface import BrokerMessage, GroupInfo, LiveChannels, PendingSummary

logger = logging.getLogger(__name__)


def _min_id(retention: timedelta) -> str:
    """The stream id below which entries are older than `retention`."""
    return f"{int((time.time() - retention.total_seconds()) * 1000)}-0"


_LAG_PAGE = 1000

# Delete first: a second mover of the same id finds nothing to delete and
# appends nothing, so a move happens once.
_MOVE_SCRIPT = """
if redis.call('XDEL', KEYS[1], ARGV[1]) == 0 then
    return false
end
return redis.call('XADD', KEYS[2], '*', unpack(ARGV, 2))
"""

#: A consumer idle this long with nothing pending belongs to a stopped process.
#: A live one reads at least every block timeout, so it is never this idle.
STOPPED_CONSUMER_IDLE = timedelta(minutes=10)

# Check and delete in one step: a consumer that reads between the two would
# lose its new pending entries with it.
_PRUNE_SCRIPT = """
local consumers = redis.pcall('XINFO', 'CONSUMERS', KEYS[1], ARGV[1])
if type(consumers) == 'table' and consumers.err then
    if string.find(consumers.err, 'NOGROUP') or string.find(consumers.err, 'no such key') then
        return 0
    end
    return consumers
end
local removed = 0
for _, consumer in ipairs(consumers) do
    local f = {}
    for i = 1, #consumer, 2 do
        f[consumer[i]] = consumer[i + 1]
    end
    if f['pending'] == 0 and f['idle'] > tonumber(ARGV[2]) then
        redis.call('XGROUP', 'DELCONSUMER', KEYS[1], ARGV[1], f['name'])
        removed = removed + 1
    end
end
return removed
"""


class RedisStreamsBroker:
    """Broker backed by Redis Streams + consumer groups.

    Stream entries are produced with `XADD`, consumed via `XREADGROUP` on a
    named consumer group, ACKed with `XACK`, and reclaimed from dead consumers
    via `XAUTOCLAIM`. `ensure_group` runs `XGROUP CREATE … MKSTREAM` so the
    first producer creates the stream lazily.

    Callers name streams logically; every Redis key is ``<namespace>.<stream>``
    and messages come back with the logical name.

    Every process start joins a group under a new consumer name. A group's
    consumers that hold nothing and were idle past `stopped_after` are removed
    when its runtime starts (`ensure_group`) and on every reclaim (`autoclaim`);
    one that still holds messages is left for `autoclaim` to empty.
    """

    def __init__(
        self,
        redis_url: str,
        *,
        namespace: str,
        stopped_after: timedelta = STOPPED_CONSUMER_IDLE,
    ) -> None:
        if not namespace:
            raise ValueError("RedisStreamsBroker needs a namespace (AGENTAREA_EVENT_NAMESPACE)")
        self._redis_url = redis_url
        self._prefix = f"{namespace}."
        self._stopped_after_ms = int(stopped_after.total_seconds() * 1000)
        self._client: redis.Redis | None = None

    def _key(self, stream: str) -> str:
        return self._prefix + stream

    def _logical(self, key: str) -> str:
        return key.removeprefix(self._prefix)

    async def _get_client(self) -> redis.Redis:
        if self._client is None:
            self._client = redis.from_url(self._redis_url, decode_responses=True)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception as exc:
                logger.debug("Redis aclose suppressed: %s", exc)
            self._client = None

    async def submit(
        self,
        stream: str,
        fields: dict[str, str],
        *,
        retention: timedelta,
    ) -> str:
        client = await self._get_client()
        msg_id: str = await client.xadd(
            self._key(stream),
            fields=cast(Any, dict(fields)),
            minid=_min_id(retention),
            approximate=True,
        )
        return msg_id

    async def ensure_group(self, stream: str, group: str, start: str = "$") -> None:
        client = await self._get_client()
        try:
            await client.xgroup_create(self._key(stream), group, id=start, mkstream=True)
        except ResponseError as exc:
            # BUSYGROUP = group already exists — that's the success path.
            if "BUSYGROUP" not in str(exc):
                raise
        await self._prune_stopped(client, stream, group)

    async def consume(
        self,
        stream: str,
        group: str,
        consumer: str,
        count: int = 10,
        block_ms: int = 5000,
    ) -> list[BrokerMessage]:
        client = await self._get_client()
        response: Any = await client.xreadgroup(
            groupname=group,
            consumername=consumer,
            streams={self._key(stream): ">"},
            count=count,
            block=block_ms,
        )
        msgs = self._flatten_xread(response)
        return await self._enrich_with_delivery_count(client, stream, group, msgs)

    async def consume_many(
        self,
        streams: list[str],
        group: str,
        consumer: str,
        count: int = 10,
        block_ms: int = 5000,
    ) -> list[BrokerMessage]:
        if not streams:
            return []
        client = await self._get_client()
        response: Any = await client.xreadgroup(
            groupname=group,
            consumername=consumer,
            streams=dict.fromkeys((self._key(s) for s in streams), ">"),
            count=count,
            block=block_ms,
        )
        by_stream: dict[str, list[BrokerMessage]] = {}
        for msg in self._flatten_xread(response):
            by_stream.setdefault(msg.stream, []).append(msg)
        out: list[BrokerMessage] = []
        for stream, msgs in by_stream.items():
            out.extend(await self._enrich_with_delivery_count(client, stream, group, msgs))
        return out

    async def ack(self, stream: str, group: str, message_id: str) -> None:
        client = await self._get_client()
        await client.xack(self._key(stream), group, message_id)

    async def autoclaim(
        self,
        stream: str,
        group: str,
        consumer: str,
        min_idle_ms: int,
        start: str = "0-0",
        count: int = 100,
    ) -> list[BrokerMessage]:
        client = await self._get_client()
        # redis-py returns (next_start_id, [(id, {fields})], deleted_ids)
        response: Any = await client.xautoclaim(
            name=self._key(stream),
            groupname=group,
            consumername=consumer,
            min_idle_time=min_idle_ms,
            start_id=start,
            count=count,
        )
        await self._prune_stopped(client, stream, group)
        if not response:
            return []
        # redis-py shape: (next_id, claimed_entries[, deleted_ids])
        claimed = response[1] if len(response) > 1 else []
        msgs = [BrokerMessage(id=mid, fields=fields, stream=stream) for mid, fields in claimed]
        return await self._enrich_with_delivery_count(client, stream, group, msgs)

    async def tail(
        self,
        stream: str,
        last_id: str = "$",
        block_ms: int = 5000,
        count: int = 100,
    ) -> tuple[str, list[BrokerMessage]]:
        client = await self._get_client()
        response: Any = await client.xread(
            streams={self._key(stream): last_id},
            count=count,
            block=block_ms,
        )
        msgs = self._flatten_xread(response)
        if not msgs:
            return last_id, []
        # Advance the cursor to the last entry so the next call returns only
        # newer entries (live tail). No ACK — this is a broadcast read.
        return msgs[-1].id, msgs

    async def group_info(self, stream: str, group: str) -> GroupInfo | None:
        client = await self._get_client()
        try:
            groups: Any = await client.xinfo_groups(self._key(stream))
        except ResponseError as exc:
            if "no such key" in str(exc):
                return None
            raise
        found = next((g for g in groups if g["name"] == group), None)
        if found is None:
            return None
        last_delivered_id = found["last-delivered-id"]
        lag = found.get("lag")
        if lag is None:
            # Redis 7+ reports no lag once entries were deleted past the
            # group's position; count what is left after it instead.
            lag = await self._count_after(client, stream, last_delivered_id)
        return GroupInfo(
            lag=int(lag),
            consumers=int(found["consumers"]),
            last_delivered_id=last_delivered_id,
        )

    async def pending_summary(self, stream: str, group: str) -> PendingSummary:
        client = await self._get_client()
        summary: Any = await client.xpending(self._key(stream), group)
        count = int(summary["pending"])
        if count == 0:
            return PendingSummary(count=0, oldest_age_ms=None)
        appended_ms = int(str(summary["min"]).split("-", 1)[0])
        return PendingSummary(
            count=count, oldest_age_ms=max(0, int(time.time() * 1000) - appended_ms)
        )

    async def length(self, stream: str) -> int:
        client = await self._get_client()
        return int(await client.xlen(self._key(stream)))

    async def read_range(
        self, stream: str, start: str = "-", end: str = "+", count: int = 100
    ) -> list[BrokerMessage]:
        client = await self._get_client()
        entries: Any = await client.xrange(self._key(stream), min=start, max=end, count=count)
        return [BrokerMessage(id=mid, fields=fields, stream=stream) for mid, fields in entries]

    async def last_id(self, stream: str) -> str:
        client = await self._get_client()
        newest: Any = await client.xrevrange(self._key(stream), max="+", min="-", count=1)
        return newest[0][0] if newest else "0-0"

    async def _prune_stopped(self, client: redis.Redis, stream: str, group: str) -> None:
        pruned = client.eval(_PRUNE_SCRIPT, 1, self._key(stream), group, self._stopped_after_ms)
        removed = int(await cast(Awaitable[int], pruned))
        if removed:
            logger.info("Removed %d stopped consumers of group %s on %s", removed, group, stream)

    async def notify(self, channel: str, fields: Mapping[str, str]) -> None:
        client = await self._get_client()
        await client.publish(self._key(channel), json.dumps(dict(fields)))

    async def open_live(self) -> LiveChannels:
        client = await self._get_client()
        return _RedisLiveChannels(client.pubsub(ignore_subscribe_messages=True), self)

    async def move(
        self, source: str, message_id: str, target: str, fields: dict[str, str]
    ) -> str | None:
        client = await self._get_client()
        flat = [item for pair in fields.items() for item in pair]
        moved = client.eval(
            _MOVE_SCRIPT, 2, self._key(source), self._key(target), message_id, *flat
        )
        return await cast(Awaitable[str | None], moved)

    async def _count_after(self, client: redis.Redis, stream: str, last_id: str) -> int:
        total = 0
        start = f"({last_id}"
        while True:
            entries: Any = await client.xrange(
                self._key(stream), min=start, max="+", count=_LAG_PAGE
            )
            total += len(entries)
            if len(entries) < _LAG_PAGE:
                return total
            start = f"({entries[-1][0]}"

    async def _enrich_with_delivery_count(
        self,
        client: redis.Redis,
        stream: str,
        group: str,
        msgs: list[BrokerMessage],
    ) -> list[BrokerMessage]:
        """Set each claimed message's `delivery_count` from its own pending entry.

        One ``XPENDING <stream> <group> <id> <id> 1`` per message, pipelined: a
        range over the batch would also count other pending entries between
        them and leave the later claimed ones uncounted, which let a message
        outlive the delivery cap.
        """
        if not msgs:
            return msgs
        async with client.pipeline(transaction=False) as pipe:
            for msg in msgs:
                pipe.xpending_range(self._key(stream), group, min=msg.id, max=msg.id, count=1)
            pending: list[Any] = await pipe.execute()
        counted: list[BrokerMessage] = []
        for msg, entries in zip(msgs, pending, strict=True):
            if not entries:
                raise RuntimeError(
                    f"message {msg.id} on {stream} was just claimed by {group} but is not pending"
                )
            counted.append(
                BrokerMessage(
                    id=msg.id,
                    fields=msg.fields,
                    delivery_count=int(entries[0]["times_delivered"]),
                    stream=msg.stream,
                )
            )
        return counted

    def _flatten_xread(self, response: Any) -> list[BrokerMessage]:
        """Normalize XREADGROUP output into a flat list of BrokerMessage.

        redis-py returns `[[stream_key, [(id, {fields}), ...]], ...]`; each
        message keeps the logical name of the stream it came from.
        """
        if not response:
            return []
        out: list[BrokerMessage] = []
        for stream_key, entries in response:
            for msg_id, fields in entries:
                out.append(
                    BrokerMessage(id=msg_id, fields=fields, stream=self._logical(stream_key))
                )
        return out


class _RedisLiveChannels:
    """Redis pub/sub on one connection; channels carry the broker's namespace."""

    def __init__(self, pubsub: Any, broker: RedisStreamsBroker) -> None:
        self._pubsub = pubsub
        self._broker = broker

    async def subscribe(self, channel: str) -> None:
        await self._pubsub.subscribe(self._broker._key(channel))

    async def unsubscribe(self, channel: str) -> None:
        await self._pubsub.unsubscribe(self._broker._key(channel))

    async def next_message(self, timeout_seconds: float) -> tuple[str, dict[str, str]] | None:
        if not self._pubsub.subscribed:
            await asyncio.sleep(timeout_seconds)
            return None
        message = await self._pubsub.get_message(timeout=timeout_seconds)
        if message is None or message.get("type") != "message":
            return None
        return self._broker._logical(message["channel"]), json.loads(message["data"])

    async def aclose(self) -> None:
        await self._pubsub.aclose()
