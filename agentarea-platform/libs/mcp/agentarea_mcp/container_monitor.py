"""MCP container monitor — pure sweep.

Every 30 s:
  1. Orphan GC: mark any `in_progress` verification older than 2 minutes as failed.
  2. Re-verify sweep: for each docker/command row with `never_attempted` verification,
     enqueue verify() (max 5 concurrent via asyncio.Semaphore).
"""

import asyncio
import logging

from agentarea_common.config import get_database
from sqlalchemy import text

logger = logging.getLogger(__name__)

_TICK_SECONDS = 30
_ORPHAN_THRESHOLD_MINUTES = 2
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
  i.json_spec,
  i.workspace_id,
  i.created_by,
  i.verification,
  i.last_dispatch,
  i.tools,
  s.json_spec AS server_json_spec,
  s.docker_image_url,
  s.remote_url,
  s.cmd
FROM mcp_server_instances i
JOIN mcp_servers s ON s.id::text = i.server_spec_id
WHERE COALESCE(
    s.json_spec->>'type',
    CASE
      WHEN s.remote_url IS NOT NULL THEN 'url'
      WHEN s.cmd IS NOT NULL THEN 'command'
      ELSE 'docker'
    END
  ) IN ('docker', 'command')
  AND (i.verification->>'status') = 'never_attempted'
  AND COALESCE((i.json_spec->>'lazy_provisioning')::boolean, false) = false
"""


class _InstanceProxy:
    """Lightweight stand-in for MCPServerInstance built from a raw SQL row.

    verify() only reads .id, .name, .json_spec, .workspace_id, .verification,
    and .endpoint_url — all of which this proxy provides without touching the
    SQLAlchemy instrumentation layer.
    """

    def __init__(self, row):
        self.id = row.id
        self.name = row.name
        transport_spec = dict(getattr(row, "server_json_spec", None) or {})
        remote_url = getattr(row, "remote_url", None)
        cmd = getattr(row, "cmd", None)
        docker_image_url = getattr(row, "docker_image_url", None)
        if remote_url:
            transport_spec.setdefault("type", "url")
            transport_spec.setdefault("endpoint_url", remote_url)
        elif cmd:
            transport_spec.setdefault("type", "command")
            if isinstance(cmd, list) and cmd:
                transport_spec.setdefault("command", cmd[0])
                if len(cmd) > 1:
                    transport_spec.setdefault("args", cmd[1:])
        elif docker_image_url:
            transport_spec.setdefault("type", "docker")
            transport_spec.setdefault("image", docker_image_url)
        else:
            transport_spec.update(row.json_spec or {})
            transport_spec.setdefault("type", "docker")
        self.json_spec = {**transport_spec, **(row.json_spec or {})}
        self.workspace_id = row.workspace_id
        self.created_by = row.created_by
        self.verification = row.verification or {}
        self.last_dispatch = row.last_dispatch
        self.tools = row.tools

    @property
    def endpoint_url(self) -> str:
        t = self.json_spec.get("type", "")
        if t == "url":
            return self.json_spec.get("endpoint_url", "")
        if t in ("docker", "command"):
            resolved = self.json_spec.get("internal_url")
            if isinstance(resolved, str) and "://" in resolved:
                return resolved
            if t == "command":
                port = 8080
            else:
                port = self.json_spec.get("port") or 8000
            return f"http://mcp-{self.id}:{port}"
        raise ValueError("bundle has no endpoint_url")


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

    async def _verify_with_semaphore(self, instance) -> None:
        async with self._semaphore:
            try:
                from agentarea_mcp.verification import verify

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
