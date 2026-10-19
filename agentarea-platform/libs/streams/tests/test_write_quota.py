"""The write quota is taken in Redis as each event is admitted, over a sliding minute.

Needs a live Redis (AGENTAREA_REDIS_URL); skipped otherwise.
"""

import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from agentarea_streams.infrastructure.write_quota import WriteQuota

REDIS_URL = os.getenv("AGENTAREA_REDIS_URL", "redis://localhost:6379")


@pytest.fixture
async def quota():
    q = WriteQuota(REDIS_URL, namespace=f"test{uuid4().hex[:8]}")
    try:
        await (await q._get_client()).ping()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Redis not reachable: {exc}")
    yield q
    await q.aclose()


async def test_a_burst_is_admitted_up_to_the_limit_and_no_further(quota):
    now = datetime(2026, 10, 15, 12, 0, 30, tzinfo=UTC)
    admitted = [await quota.take("ws", 600, now) for _ in range(636)]
    assert admitted.count(True) == 600


async def test_the_previous_minute_weighs_in_as_the_window_slides(quota):
    full = datetime(2026, 10, 15, 12, 0, 59, tzinfo=UTC)
    for _ in range(10):
        assert await quota.take("ws", 10, full)
    early_next = datetime(2026, 10, 15, 12, 1, 3, tzinfo=UTC)
    assert not await quota.take("ws", 10, early_next)
    late_next = datetime(2026, 10, 15, 12, 1, 57, tzinfo=UTC)
    assert await quota.take("ws", 10, late_next)


async def test_workspaces_have_their_own_quota(quota):
    now = datetime(2026, 10, 15, 12, 0, 0, tzinfo=UTC)
    assert await quota.take("a", 1, now)
    assert not await quota.take("a", 1, now)
    assert await quota.take("b", 1, now)
