"""The daily pulse: one ``installation_pulse`` event of counts from the database.

Runs inside the worker. Every replica ticks hourly; the one holding the pulse lock
sends when a day has passed since the installation's last pulse.
"""

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentarea_common.base.tenant_scope import unscoped

from .pulse_repository import collect_pulse, try_pulse_lock
from .repository import get_or_create_installation
from .sender import AnalyticsSender

logger = logging.getLogger(__name__)


class InstallationPulse:
    """Sends the installation's pulse at most once a day, from one replica."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        sender: AnalyticsSender,
        tick: timedelta = timedelta(hours=1),
        every: timedelta = timedelta(days=1),
        clock: Callable[[], datetime] = datetime.now,
    ) -> None:
        self._session_factory = session_factory
        self._sender = sender
        self._tick = tick
        self._every = every
        # Naive local time, as the columns the pulse compares it with are written.
        self._clock = clock
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run_loop(), name="installation-pulse")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run_loop(self) -> None:
        while True:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("Installation pulse failed; retried next tick", exc_info=True)
            await asyncio.sleep(self._tick.total_seconds())

    async def run_once(self) -> bool:
        """Send the pulse if it is due and this replica holds the lock; whether it was sent."""
        now = self._clock()
        with unscoped("the installation pulse counts every workspace of the installation"):
            async with self._session_factory() as session:
                if not await try_pulse_lock(session):
                    return False
                installation = await get_or_create_installation(session)
                last = installation.last_pulse_at
                if last is not None and now - last < self._every:
                    return False
                properties = {
                    "install_age_days": (now - installation.created_at).days,
                    **await collect_pulse(session, now),
                }
                installation.last_pulse_at = now
                await session.commit()
        self._sender.enqueue({"event": "installation_pulse", "properties": properties})
        await self._sender.flush()
        return True
