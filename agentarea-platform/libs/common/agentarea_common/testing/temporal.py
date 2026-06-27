"""Shared pytest fixtures for running tests against a real Temporal server.

Import these into a ``conftest.py`` to make them available to that package's
tests::

    from agentarea_common.testing.temporal import (  # noqa: F401
        temporal_sqlite_client,
        temporal_sqlite_env,
    )

Why a real server? ``WorkflowEnvironment.start_time_skipping()`` (the in-memory
Java test server) is great for workflow tests because it fast-forwards time, but
it does NOT implement several server features -- notably the Schedules API.
``start_local()`` runs the actual Temporal server backed by SQLite, so it is
faithful (schedules, visibility, etc.) at the cost of losing time-skipping.

Rule of thumb:
- Need fast timers / ``workflow.sleep`` to elapse instantly -> ``start_time_skipping``.
- Need faithful server behaviour (schedules, real persistence) -> these fixtures.
"""

from __future__ import annotations

import os
import tempfile

import pytest_asyncio

__all__ = ["temporal_download_dir", "temporal_sqlite_client", "temporal_sqlite_env"]


def temporal_download_dir() -> str:
    """Shared download directory for the Temporal dev-server binary.

    Reused by both the time-skipping test server and the SQLite ``start_local``
    server so CI downloads the binary at most once. Honours
    ``TEMPORAL_TEST_SERVER_DOWNLOAD_DIR`` when set.
    """
    download_dir = os.environ.get("TEMPORAL_TEST_SERVER_DOWNLOAD_DIR")
    if not download_dir:
        download_dir = os.path.join(tempfile.gettempdir(), "agentarea-temporal-test-server")
    os.makedirs(download_dir, exist_ok=True)
    return download_dir


@pytest_asyncio.fixture
async def temporal_sqlite_env():
    """A real, SQLite-backed Temporal server via ``WorkflowEnvironment.start_local()``.

    Unlike ``start_time_skipping()`` (the in-memory Java test server), this runs the
    actual Temporal server on SQLite, so it supports features the test server does
    not -- notably the Schedules API. Use it for tests that exercise schedules or
    need faithful server behaviour.

    Trade-off: there is NO time-skipping. Timers and ``workflow.sleep`` wait real
    wall-clock time, so do not use this for tests that rely on fast-forwarding time;
    keep those on ``start_time_skipping()``.

    The client uses the pydantic data converter to match production encoding
    (e.g. UUID workflow arguments).
    """
    from temporalio.contrib.pydantic import pydantic_data_converter
    from temporalio.testing import WorkflowEnvironment

    env = await WorkflowEnvironment.start_local(
        data_converter=pydantic_data_converter,
        download_dest_dir=temporal_download_dir(),
    )
    try:
        yield env
    finally:
        await env.shutdown()


@pytest_asyncio.fixture
async def temporal_sqlite_client(temporal_sqlite_env):
    """Temporal client connected to the SQLite-backed dev server.

    Convenience wrapper around :func:`temporal_sqlite_env` for tests that only
    need the client (e.g. schedule-management tests).
    """
    return temporal_sqlite_env.client
