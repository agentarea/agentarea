from uuid import uuid4

from agentarea_streams.infrastructure.waker import WAKE_CHANNEL, RedisStreamWaker
from redis.exceptions import ConnectionError as RedisConnectionError


class _Redis:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.published: list[tuple[str, str]] = []

    async def publish(self, channel, message):
        if self.fail:
            raise RedisConnectionError("down")
        self.published.append((channel, message))


async def test_wake_publishes_the_stream_id():
    waker = RedisStreamWaker("redis://unused")
    waker._client = _Redis()
    stream = uuid4()
    await waker.wake(stream)
    assert waker._client.published == [(WAKE_CHANNEL, str(stream))]


async def test_a_lost_wake_is_logged_not_raised(caplog):
    waker = RedisStreamWaker("redis://unused")
    waker._client = _Redis(fail=True)
    await waker.wake(uuid4())
    assert "poll picks it up" in caplog.text
