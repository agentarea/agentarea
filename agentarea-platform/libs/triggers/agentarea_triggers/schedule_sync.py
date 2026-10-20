"""Every cron trigger's Temporal Schedule brought to what the triggers table says.

The table is the truth and a schedule is its copy. A trigger is written first
and its schedule after; when the second step fails (Temporal down, a lost
update) the two disagree, and a restored Temporal has lost every schedule. A
trigger that reads active and never fires says nothing, so this pass, run by a
schedule of its own, repairs whatever drifted.

It never deletes a schedule: another deployment can share the Temporal
namespace, and a trigger being created has its schedule before its row is
committed. A schedule whose trigger is gone fails its firing, as it always did.
"""

import logging
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from agentarea_common.base.tenant_scope import unscoped
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .domain.enums import TriggerType
from .infrastructure.orm import TriggerORM

logger = logging.getLogger(__name__)


class CronSchedules(Protocol):
    async def apply_cron_schedule(
        self, trigger_id: UUID, cron_expression: str, timezone: str, *, paused: bool
    ) -> bool: ...


@dataclass(frozen=True)
class CronRow:
    id: UUID
    cron_expression: str | None
    timezone: str | None
    is_active: bool


@dataclass(frozen=True)
class ScheduleSyncReport:
    changed: int
    failed: int


async def _cron_rows(
    session_factory: async_sessionmaker[AsyncSession], trigger_id: UUID | None = None
) -> list[CronRow]:
    query = select(
        TriggerORM.id, TriggerORM.cron_expression, TriggerORM.timezone, TriggerORM.is_active
    ).where(TriggerORM.trigger_type == TriggerType.CRON.value)
    if trigger_id is not None:
        query = query.where(TriggerORM.id == trigger_id)
    with unscoped("the schedule sync reads every workspace's cron triggers"):
        async with session_factory() as session:
            return [CronRow(*row) for row in await session.execute(query)]


async def sync_cron_schedules(
    session_factory: async_sessionmaker[AsyncSession], schedules: CronSchedules
) -> ScheduleSyncReport:
    """Apply every cron trigger's schedule as its row stands when it is applied.

    Each row is read again just before its schedule is applied, so an edit or a
    delete made while the pass runs is not undone. One schedule Temporal refuses
    is logged and left to the next pass; the rest go on.
    """
    changed = failed = 0
    for listed in await _cron_rows(session_factory):
        current = await _cron_rows(session_factory, listed.id)
        if not current:
            continue
        row = current[0]
        if not row.cron_expression:
            logger.error("Cron trigger %s has no cron expression; it has no schedule", row.id)
            failed += 1
            continue
        try:
            if await schedules.apply_cron_schedule(
                row.id, row.cron_expression, row.timezone or "UTC", paused=not row.is_active
            ):
                changed += 1
        except Exception:
            logger.error(
                "Could not bring the schedule of trigger %s in line", row.id, exc_info=True
            )
            failed += 1

    if changed or failed:
        logger.info("Schedule sync: %d brought in line, %d failed", changed, failed)
    return ScheduleSyncReport(changed=changed, failed=failed)
