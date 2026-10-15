"""Redis Streams implementation of `BrokerClient`."""

from __future__ import annotations

import logging
from collections.abc import Awaitable
from typing import Any, cast

import redis.asyncio as redis
from redis.exceptions import ResponseError

from .interface import BrokerMessage, GroupInfo, PendingSummary

logger = logging.getLogger(__name__)

_PENDING_PAGE = 1000
_LAG_PAGE = 1000

# Delete first: a second mover of the same id finds nothing to delete and
# appends nothing, so a move happens once.
_MOVE_SCRIPT = """
if redis.call('XDEL', KEYS[1], ARGV[1]) == 0 then
    return false
end
return redis.call('XADD', KEYS[2], '*', unpack(ARGV, 2))
"""


class RedisStreamsBroker:
    """Broker backed by Redis Streams + consumer groups.

    Stream entries are produced with `XADD`, consumed via `XREADGROUP` on a
    named consumer group, ACKed with `XACK`, and reclaimed from dead consumers
    via `XAUTOCLAIM`. `ensure_group` runs `XGROUP CREATE … MKSTREAM` so the
    first producer creates the stream lazily.

    Callers name streams logically; every Redis key is ``<namespace>.<stream>``
    and messages come back with the logical name.
    """

    def __init__(self, redis_url: str, *, namespace: str) -> None:
        if not namespace:
            raise ValueError("RedisStreamsBroker needs a namespace (AGENTAREA_EVENT_NAMESPACE)")
        self._redis_url = redis_url
        self._prefix = f"{namespace}."
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
        maxlen: int | None = None,
        ttl_seconds: int | None = None,
    ) -> str:
        client = await self._get_client()
        kwargs: dict[str, Any] = {}
        if maxlen is not None:
            kwargs["maxlen"] = maxlen
            kwargs["approximate"] = True
        if ttl_seconds is None:
            msg_id: str = await client.xadd(
                self._key(stream), fields=cast(Any, dict(fields)), **kwargs
            )
            return msg_id
        async with client.pipeline(transaction=True) as pipe:
            pipe.xadd(self._key(stream), fields=cast(Any, dict(fields)), **kwargs)
            pipe.expire(self._key(stream), ttl_seconds)
            msg_id, _ = await pipe.execute()
        return msg_id

    async def ensure_group(self, stream: str, group: str, start: str = "$") -> None:
        client = await self._get_client()
        try:
            await client.xgroup_create(self._key(stream), group, id=start, mkstream=True)
        except ResponseError as exc:
            # BUSYGROUP = group already exists — that's the success path.
            if "BUSYGROUP" in str(exc):
                return
            raise

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
            return PendingSummary(count=0, oldest_idle_ms=None)
        oldest = 0
        start = "-"
        while True:
            page: Any = await client.xpending_range(
                self._key(stream), group, min=start, max="+", count=_PENDING_PAGE
            )
            for entry in page:
                oldest = max(oldest, int(entry["time_since_delivered"]))
            if len(page) < _PENDING_PAGE:
                break
            start = f"({page[-1]['message_id']}"
        return PendingSummary(count=count, oldest_idle_ms=oldest)

    async def length(self, stream: str) -> int:
        client = await self._get_client()
        return int(await client.xlen(self._key(stream)))

    async def read_range(
        self, stream: str, start: str = "-", end: str = "+", count: int = 100
    ) -> list[BrokerMessage]:
        client = await self._get_client()
        entries: Any = await client.xrange(self._key(stream), min=start, max=end, count=count)
        return [BrokerMessage(id=mid, fields=fields, stream=stream) for mid, fields in entries]

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
        """Backfill `delivery_count` on each message via a single
        `XPENDING ... IDLE 0 min max count` over the claimed batch.

        Redis Streams tracks delivery_count per pending entry; the count
        only exists once XREADGROUP/XAUTOCLAIM has claimed the entry, so
        we read it right after the claim. One round-trip per batch.
        """
        if not msgs:
            return msgs
        ids = [m.id for m in msgs]
        try:
            # XPENDING <stream> <group> IDLE 0 <min> <max> <count> bounded
            # by the batch range. redis-py returns dicts:
            # [{"message_id", "consumer", "time_since_delivered", "times_delivered"}, ...]
            pending: Any = await client.xpending_range(
                self._key(stream),
                group,
                min=ids[0],
                max=ids[-1],
                count=len(ids),
            )
        except Exception as exc:
            logger.debug("XPENDING enrich failed, defaulting delivery_count=1: %s", exc)
            return msgs

        by_id = {p["message_id"]: int(p["times_delivered"]) for p in (pending or [])}
        return [
            BrokerMessage(
                id=m.id,
                fields=m.fields,
                delivery_count=by_id.get(m.id, m.delivery_count),
                stream=m.stream,
            )
            for m in msgs
        ]

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
