"""OutboxRelay — background loop that drains the transactional outbox.

Runs inside the existing worker (no new app unit). Each pass:

1. ``fetch_unpublished`` under ``SELECT ... FOR UPDATE SKIP LOCKED`` so multiple
   relay instances share the load without coordination.
2. publish each row's envelope to the real broker (raw redis via RedisEventBroker).
3. ``mark_published`` on success; on failure ``mark_failed`` (records the error,
   increments ``attempts``) and leaves the row for a later retry.

Rows that exceed ``max_attempts`` are logged loudly and skipped so a permanently
poisoned event cannot wedge the loop — they are never silently dropped.
"""

from __future__ import annotations

import asyncio
import logging

from agentarea_common.auth.context import UserContext
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .base_events import EventEnvelope
from .broker import EventBroker
from .outbox_repository import OutboxRepository

logger = logging.getLogger(__name__)

# The relay is infrastructure and reads across all workspaces; the repository
# only needs a context object for its constructor, never for scoping the fetch.
_RELAY_CONTEXT = UserContext(user_id="outbox-relay", workspace_id="outbox-relay")


class OutboxRelay:
    """Publishes outbox rows to the broker on a bounded interval."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        event_broker: EventBroker,
        interval_seconds: float = 1.0,
        batch_size: int = 100,
        max_attempts: int = 10,
    ) -> None:
        self._session_factory = session_factory
        self._event_broker = event_broker
        self._interval = interval_seconds
        self._batch_size = batch_size
        self._max_attempts = max_attempts
        self._task: asyncio.Task[None] | None = None
        self._running = False

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop(), name="outbox-relay")
        logger.info(
            "OutboxRelay started (interval=%.1fs batch=%d)", self._interval, self._batch_size
        )

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("OutboxRelay stopped")

    async def _run_loop(self) -> None:
        while self._running:
            try:
                await self.process_batch()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("OutboxRelay batch failed")
            await asyncio.sleep(self._interval)

    async def process_batch(self) -> int:
        """Publish one batch of pending rows. Returns the count published.

        Each row is committed independently: publishing to the broker is an
        external side effect, so we mark the row published in its own commit to
        avoid re-publishing on a later crash. One session/transaction wraps the
        locked ``fetch`` so ``FOR UPDATE SKIP LOCKED`` holds for the whole batch.
        """
        published = 0
        async with self._session_factory() as session:
            repo = OutboxRepository(session, _RELAY_CONTEXT)
            rows = await repo.fetch_unpublished(limit=self._batch_size)
            for row in rows:
                if row.attempts >= self._max_attempts:
                    logger.error(
                        "OutboxRelay giving up on event %s (type=%s) after %d attempts: %s",
                        row.event_id,
                        row.event_type,
                        row.attempts,
                        row.last_error,
                    )
                    continue
                try:
                    envelope = EventEnvelope.from_dict(row.payload)
                    await self._event_broker.publish(envelope)
                except Exception as exc:
                    logger.error(
                        "OutboxRelay failed to publish event %s (type=%s): %s",
                        row.event_id,
                        row.event_type,
                        exc,
                        exc_info=True,
                    )
                    await repo.mark_failed(row.id, str(exc))
                else:
                    await repo.mark_published(row.id)
                    published += 1
            await session.commit()
        return published
