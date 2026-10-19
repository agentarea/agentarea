"""The activities of a trigger's batch workflow: fire the batch, or close it unfired."""

from typing import TYPE_CHECKING

from temporalio import activity

from ..workflows.trigger_batch_workflow import (
    CLOSE_TRIGGER_BATCH,
    FIRE_TRIGGER_BATCH,
    OpenBatch,
)

if TYPE_CHECKING:
    from agentarea_triggers.batch_firing import TriggerBatchFirer


def make_trigger_batch_activities(firer: "TriggerBatchFirer"):
    @activity.defn(name=FIRE_TRIGGER_BATCH)
    async def fire_trigger_batch_activity(batch: OpenBatch) -> int:
        return await firer.fire(batch)

    @activity.defn(name=CLOSE_TRIGGER_BATCH)
    async def close_trigger_batch_activity(batch: OpenBatch) -> int:
        return await firer.close(batch)

    return [fire_trigger_batch_activity, close_trigger_batch_activity]
