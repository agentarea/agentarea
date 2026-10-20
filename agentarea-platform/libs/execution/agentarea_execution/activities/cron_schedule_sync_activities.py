"""The activity that brings every cron trigger's schedule to what its trigger says."""

from agentarea_common.config import get_database
from agentarea_triggers.schedule_sync import sync_cron_schedules
from agentarea_triggers.temporal_schedule_manager import TemporalScheduleManager
from temporalio import activity

from ..workflows.cron_schedule_sync_workflow import SYNC_CRON_SCHEDULES


def make_cron_schedule_sync_activities(schedules: TemporalScheduleManager):
    @activity.defn(name=SYNC_CRON_SCHEDULES)
    async def sync_cron_schedules_activity() -> None:
        await sync_cron_schedules(get_database().async_session_factory, schedules)

    return [sync_cron_schedules_activity]
