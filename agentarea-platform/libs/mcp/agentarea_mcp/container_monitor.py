"""MCP container monitor — pure sweep.

Every 30 s:
  1. Orphan GC: mark any `in_progress` verification older than 2 minutes as failed.
  2. Re-verify sweep: for each docker/command row with `never_attempted` verification,
     enqueue verify() (max 5 concurrent via asyncio.Semaphore).
  3. Package import sweep: import verified npx/uvx command rows sequentially (max 3).
"""

import asyncio
import logging

from agentarea_common.base.tenant_scope import unscoped, workspace_scope
from agentarea_common.config import get_database
from sqlalchemy import text

from agentarea_mcp.domain.transport import MCPTransport
from agentarea_mcp.infrastructure.repository import MCPServerInstanceRepository
from agentarea_mcp.package_import import import_package_image

logger = logging.getLogger(__name__)

_TICK_SECONDS = 30
# Crash-recovery backstop: a verification stuck in `in_progress` is reaped only
# once it is older than this. It MUST exceed the longest a healthy verify() can
# run (verification._SAFETY_DEADLINE, 600s) so the GC never kills a verify that
# is still legitimately waiting on a slow cold `uvx`/`npx` install — it only
# cleans up rows orphaned by a crashed/restarted worker.
_ORPHAN_THRESHOLD_MINUTES = 12
_MAX_CONCURRENT_VERIFICATIONS = 5

_ORPHAN_GC_SQL = """
UPDATE mcp_server_instances
SET verification = jsonb_set(
      jsonb_set(
        verification,
        '{status}',
        '"failed"'::jsonb
      ),
      '{error}',
      jsonb_build_object(
        'code', 'verification_interrupted',
        'message', 'Verification timed out — click Verify to retry.',
        'detail', NULL
      )
    )
WHERE (verification->>'status') = 'in_progress'
  AND (verification->>'at')::timestamptz < now() - make_interval(mins => :threshold_minutes)
"""

_NEVER_ATTEMPTED_SQL = """
SELECT
  i.id,
  i.name,
  i.transport,
  i.json_spec,
  i.workspace_id,
  i.created_by,
  i.verification,
  i.last_dispatch,
  i.tools
FROM mcp_server_instances i
WHERE i.transport IN ('docker', 'command')
  AND (i.verification->>'status') = 'never_attempted'
"""


class _InstanceProxy:
    """Lightweight stand-in for MCPServerInstance built from a raw SQL row.

    verify() reads .id and .transport from it, then locks and reloads the row
    itself, so nothing here touches the SQLAlchemy instrumentation layer.
    """

    def __init__(self, row):
        self.id = row.id
        self.name = row.name
        self.transport = MCPTransport(row.transport)
        self.json_spec = row.json_spec or {}
        self.workspace_id = row.workspace_id
        self.created_by = row.created_by
        self.verification = row.verification or {}
        self.last_dispatch = row.last_dispatch
        self.tools = row.tools


class MCPContainerMonitor:
    """Monitor that sweeps DB rows and drives verification state transitions."""

    def __init__(self, check_interval: int = _TICK_SECONDS):
        self.check_interval = check_interval
        self.is_running = False
        self._semaphore = asyncio.Semaphore(_MAX_CONCURRENT_VERIFICATIONS)
        self._background_task: asyncio.Task[None] | None = None
        self._background_tasks: set[asyncio.Task[None]] = set()

    async def start(self) -> None:
        if self.is_running:
            logger.warning("MCPContainerMonitor is already running")
            return

        self.is_running = True
        logger.info("MCPContainerMonitor starting (interval=%ds)", self.check_interval)

        while self.is_running:
            try:
                await self._tick()
            except Exception:
                logger.exception("MCPContainerMonitor tick raised unexpectedly")
            await asyncio.sleep(self.check_interval)

    async def stop(self) -> None:
        self.is_running = False
        logger.info("MCPContainerMonitor stopped")

    async def _tick(self) -> None:
        db = get_database()
        async with db.async_session_factory() as session:
            # 1. Orphan GC
            result = await session.execute(
                text(_ORPHAN_GC_SQL),
                {"threshold_minutes": _ORPHAN_THRESHOLD_MINUTES},
            )
            await session.commit()
            reaped = int(getattr(result, "rowcount", 0) or 0)
            if reaped:
                logger.info("orphan gc: %d rows reaped", reaped, extra={"reaped": reaped})
            else:
                logger.debug("orphan gc: 0 rows reaped")

            # 2. Re-verify sweep
            rows_result = await session.execute(text(_NEVER_ATTEMPTED_SQL))
            rows = rows_result.fetchall()

            # 3. Package import sweep. The import function opens no concurrent
            # work of its own, so awaiting each row keeps imports sequential.
            with unscoped("the package-import sweep reads every workspace's command connections"):
                package_rows = await MCPServerInstanceRepository.list_package_import_candidates(
                    session,
                    limit=3,
                )

        enqueued = 0
        for row in rows:
            instance = await self._row_to_instance(row)
            if instance is None:
                continue
            enqueued += 1
            task = asyncio.create_task(self._verify_with_semaphore(instance))
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)

        logger.info(
            "verify sweep: %d rows enqueued",
            enqueued,
            extra={"enqueued": enqueued},
        )

        imported = 0
        for row in package_rows:
            imported += 1
            try:
                # The import reads and writes one connection; bind its
                # workspace like verification does, or enforce refuses it.
                with workspace_scope(str(row.workspace_id)):
                    await import_package_image(row.id)
            except Exception:
                logger.exception(
                    "package import raised for instance %s",
                    row.id,
                    extra={"instance_id": str(row.id)},
                )

        logger.info(
            "package import sweep: %d rows attempted",
            imported,
            extra={"attempted": imported},
        )

    async def _verify_with_semaphore(self, instance) -> None:
        async with self._semaphore:
            try:
                from agentarea_mcp.verification import verify

                with workspace_scope(str(instance.workspace_id)):
                    await verify(instance)
            except Exception:
                logger.exception(
                    "verify raised for instance %s",
                    instance.id,
                    extra={"instance_id": str(instance.id)},
                )

    async def _row_to_instance(self, row):
        """Convert a raw SQL row to a lightweight object suitable for verify()."""
        try:
            return _InstanceProxy(row)
        except Exception:
            logger.exception("Failed to hydrate instance row %s", row.id)
            return None


# Module-level singleton kept for worker startup hook compatibility.
_monitor_instance: MCPContainerMonitor | None = None


def get_container_monitor(check_interval: int = _TICK_SECONDS) -> MCPContainerMonitor:
    global _monitor_instance
    if _monitor_instance is None:
        _monitor_instance = MCPContainerMonitor(check_interval=check_interval)
    return _monitor_instance


async def start_container_monitoring() -> MCPContainerMonitor:
    """Start container monitoring in a background task."""
    monitor = get_container_monitor()
    task = asyncio.create_task(monitor.start())
    monitor._background_task = task
    return monitor


async def stop_container_monitoring() -> None:
    global _monitor_instance
    if _monitor_instance and _monitor_instance.is_running:
        await _monitor_instance.stop()
