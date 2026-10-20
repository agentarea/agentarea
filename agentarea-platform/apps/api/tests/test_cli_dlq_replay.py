"""`agentarea-api dlq-replay` against a live Redis; skipped when AGENTAREA_REDIS_URL is unreachable."""

import asyncio
import os
import uuid
from datetime import timedelta

import pytest
from agentarea_api.cli import cli
from agentarea_common.broker import RedisStreamsBroker
from agentarea_common.broker.topics import INGEST_GROUP, STREAMS_INGEST, dead_letter_topic
from click.testing import CliRunner

REDIS_URL = os.getenv("AGENTAREA_REDIS_URL", "redis://localhost:6379")


# A namespace per run keeps the fixed topic names of one run apart from another's.
NAMESPACE = f"test-cli-replay-{uuid.uuid4().hex[:12]}"


@pytest.fixture()
def channel(monkeypatch) -> tuple[str, str]:
    monkeypatch.setenv("AGENTAREA_BROKER", "redis")
    monkeypatch.setenv("AGENTAREA_REDIS_URL", REDIS_URL)
    monkeypatch.setenv("AGENTAREA_EVENT_NAMESPACE", NAMESPACE)
    return STREAMS_INGEST, dead_letter_topic(STREAMS_INGEST, INGEST_GROUP)


async def _seed(dlq: str) -> list[str]:
    broker = RedisStreamsBroker(REDIS_URL, namespace=NAMESPACE)
    try:
        return [
            await broker.submit(
                dlq, {"n": str(n), "fatal_reason": "boom"}, retention=timedelta(hours=1)
            )
            for n in range(3)
        ]
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Redis not reachable: {exc}")
    finally:
        await broker.aclose()


async def _fields(stream: str) -> list[dict[str, str]]:
    broker = RedisStreamsBroker(REDIS_URL, namespace=NAMESPACE)
    try:
        return [m.fields for m in await broker.read_range(stream)]
    finally:
        await broker.aclose()


async def test_replays_a_configured_dead_letter_stream_to_its_source(channel):
    stream, dlq = channel
    ids = await _seed(dlq)

    result = await _invoke(["dlq-replay", dlq, "--start", ids[1]])

    assert result.exit_code == 0, result.output
    assert "Replayed 2" in result.output
    assert await _fields(stream) == [{"n": "1"}, {"n": "2"}]
    assert await _fields(dlq) == [{"n": "0", "fatal_reason": "boom"}]


async def test_an_unknown_dead_letter_stream_is_refused(channel):
    result = await _invoke(["dlq-replay", "router.dlq"])

    assert result.exit_code != 0
    assert "not a configured dead-letter stream" in result.output


async def _invoke(args: list[str]):
    return await asyncio.to_thread(CliRunner().invoke, cli, args)
