"""Every cron trigger's Temporal Schedule brought to what the triggers table says.

The table is the truth and a schedule is its copy. A trigger is written first
and its schedule after; when the second step fails (Temporal down, a lost
update) the two disagree, and a restored Temporal has lost every schedule. A
trigger that reads active and never fires says nothing, so this pass, run by a
schedule of its own, repairs whatever drifted and deletes the schedules of
triggers that are gone.
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

    async def delete_cron_schedules_except(self, keep: set[UUID]) -> int: ...


@dataclass(frozen=True)
class ScheduleSyncReport:
    changed: int
    removed: int
    failed: int


async def sync_cron_schedules(
    session_factory: async_sessionmaker[AsyncSession], schedules: CronSchedules
) -> ScheduleSyncReport:
    """Apply every cron trigger's schedule, then delete the schedules no trigger owns.

    One schedule Temporal refuses is logged and left to the next pass; the rest go on.
    """
    with unscoped("the schedule sync reads every workspace's cron triggers"):
        async with session_factory() as session:
            rows = (
                await session.execute(
                    select(
                        TriggerORM.id,
                        TriggerORM.cron_expression,
                        TriggerORM.timezone,
                        TriggerORM.is_active,
                    ).where(TriggerORM.trigger_type == TriggerType.CRON.value)
                )
            ).all()

    changed = failed = 0
    for row in rows:
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

    removed = await schedules.delete_cron_schedules_except({row.id for row in rows})
    if changed or removed or failed:
        logger.info(
            "Schedule sync: %d brought in line, %d of gone triggers deleted, %d failed",
            changed,
            removed,
            failed,
        )
    return ScheduleSyncReport(changed=changed, removed=removed, failed=failed)
