"""Redis Streams implementation of `BrokerClient`."""

from __future__ import annotations

import logging
from typing import Any

import redis.asyncio as redis
from redis.exceptions import ResponseError

from .interface import BrokerMessage

logger = logging.getLogger(__name__)


class RedisStreamsBroker:
    """Broker backed by Redis Streams + consumer groups.

    Stream entries are produced with `XADD`, consumed via `XREADGROUP` on a
    named consumer group, ACKed with `XACK`, and reclaimed from dead consumers
    via `XAUTOCLAIM`. `ensure_group` runs `XGROUP CREATE … MKSTREAM` so the
    first producer creates the stream lazily.
    """

    def __init__(self, redis_url: str) -> None:
        self._redis_url = redis_url
        self._client: redis.Redis | None = None

    async def _get_client(self) -> redis.Redis:
        if self._client is None:
            self._client = redis.from_url(self._redis_url, decode_responses=True)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception as exc:  # noqa: BLE001
                logger.debug("Redis aclose suppressed: %s", exc)
            self._client = None

    async def submit(self, stream: str, fields: dict[str, str]) -> str:
        client = await self._get_client()
        msg_id: str = await client.xadd(stream, fields)
        return msg_id

    async def ensure_group(
        self, stream: str, group: str, start: str = "$"
    ) -> None:
        client = await self._get_client()
        try:
            await client.xgroup_create(stream, group, id=start, mkstream=True)
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
            streams={stream: ">"},
            count=count,
            block=block_ms,
        )
        msgs = _flatten_xread(response)
        return await self._enrich_with_delivery_count(client, stream, group, msgs)

    async def ack(self, stream: str, group: str, message_id: str) -> None:
        client = await self._get_client()
        await client.xack(stream, group, message_id)

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
            name=stream,
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
        msgs = [BrokerMessage(id=mid, fields=fields) for mid, fields in claimed]
        return await self._enrich_with_delivery_count(client, stream, group, msgs)

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
                stream,
                group,
                min=ids[0],
                max=ids[-1],
                count=len(ids),
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("XPENDING enrich failed, defaulting delivery_count=1: %s", exc)
            return msgs

        by_id = {p["message_id"]: int(p["times_delivered"]) for p in (pending or [])}
        return [
            BrokerMessage(
                id=m.id,
                fields=m.fields,
                delivery_count=by_id.get(m.id, m.delivery_count),
            )
            for m in msgs
        ]


def _flatten_xread(response: Any) -> list[BrokerMessage]:
    """Normalize XREADGROUP output into a flat list of BrokerMessage.

    redis-py returns `[[stream_name, [(id, {fields}), ...]], ...]`. We only
    ever request one stream per call, so we flatten the outer wrapping away.
    """
    if not response:
        return []
    out: list[BrokerMessage] = []
    for _stream_name, entries in response:
        for msg_id, fields in entries:
            out.append(BrokerMessage(id=msg_id, fields=fields))
    return out
