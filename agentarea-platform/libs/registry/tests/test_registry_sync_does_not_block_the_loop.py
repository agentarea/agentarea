"""Fetching a catalog must not stop the API answering everything else.

The API runs one uvicorn worker per pod, so one event loop serves every
request. `_fetch_source` is a synchronous `urllib.request.urlopen`, and it used
to be called straight from `sync_registry`, a coroutine. A slow catalog host
therefore froze the whole process -- including `/health`, which is what the
readiness and liveness probes poll, so a hung fetch took the pod out of the
Service and then had it restarted.
"""

import asyncio
import threading
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from agentarea_registry.application.service import RegistryService

# How long the stand-in fetch holds its thread. Long enough that a blocked loop
# is unmistakable in the measurement below, short enough not to drag the suite.
FETCH_BLOCKS_FOR = 3.0


def _service():
    registry = SimpleNamespace(
        id=uuid4(),
        registry_type="llm_models",
        source_type="url",
        source_url="https://example.com/catalog.json",
    )
    registry_repo = SimpleNamespace(
        get_by_id=AsyncMock(return_value=registry),
        update=AsyncMock(),
    )
    item_repo = SimpleNamespace(
        get_by_external_id=AsyncMock(return_value=None),
        create=AsyncMock(return_value=SimpleNamespace(id=uuid4())),
        update=AsyncMock(),
        delete=AsyncMock(return_value=True),
        session=SimpleNamespace(commit=AsyncMock(), refresh=AsyncMock()),
    )
    service = RegistryService(
        registry_repo,
        item_repo,
        server_repo=None,
        provider_spec_repo=SimpleNamespace(get_by_provider_key=AsyncMock(return_value=None)),
        model_spec_repo=SimpleNamespace(upsert_by_provider_and_model_kwargs=AsyncMock()),
    )
    return service, registry


async def test_a_slow_catalog_fetch_leaves_the_event_loop_free():
    """An unrelated coroutine keeps its schedule while the fetch is in flight.

    Measured with a heartbeat rather than one timed sleep: a blocked loop stalls
    wherever the fetch happens to land, which is not necessarily inside the
    window a single measurement covers.
    """
    service, registry = _service()
    release = threading.Event()

    def blocking_fetch(source_url: str) -> dict:
        release.wait(FETCH_BLOCKS_FOR)
        return {"models": []}

    beats: list[float] = []
    beating = True

    async def heartbeat():
        while beating:
            beats.append(time.monotonic())
            await asyncio.sleep(0.01)

    pulse = asyncio.create_task(heartbeat())
    await asyncio.sleep(0.05)

    with patch.object(RegistryService, "_fetch_source", staticmethod(blocking_fetch)):
        sync = asyncio.create_task(service.sync_registry(registry.id))
        await asyncio.sleep(0.2)
        release.set()
        await asyncio.wait_for(sync, timeout=FETCH_BLOCKS_FOR + 5)

    beating = False
    await pulse

    longest_gap = max(b - a for a, b in zip(beats, beats[1:], strict=False))
    assert longest_gap < 1.0, (
        f"the event loop stalled for {longest_gap:.2f}s during the catalog fetch: "
        "_fetch_source is running on the loop instead of a worker thread"
    )
