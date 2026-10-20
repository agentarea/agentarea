"""The router's side of a batch: signal-with-start through the workflow executor."""

import uuid
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from agentarea_common.workflow.sandbox import create_workflow_runner
from agentarea_common.workflow.temporal_executor import TemporalWorkflowExecutor
from agentarea_execution.workflows.trigger_batch_workflow import (
    CLOSE_TRIGGER_BATCH,
    FIRE_TRIGGER_BATCH,
    BatchSpec,
    OpenBatch,
    TriggerBatchWorkflow,
)
from agentarea_triggers.batches import TemporalTriggerBatches, batch_workflow_id
from temporalio import activity
from temporalio.client import WorkflowExecutionStatus
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker


@pytest.mark.asyncio
async def test_the_first_event_opens_the_batch_and_the_next_joins_it():
    fired: list[list[UUID]] = []

    @activity.defn(name=FIRE_TRIGGER_BATCH)
    async def fire(batch: OpenBatch) -> int:
        fired.append(batch.event_ids)
        return len(batch.event_ids)

    @activity.defn(name=CLOSE_TRIGGER_BATCH)
    async def close(batch: OpenBatch) -> int:
        return 0

    async with await WorkflowEnvironment.start_time_skipping(
        data_converter=pydantic_data_converter
    ) as env:
        queue = str(uuid.uuid4())
        batches = TemporalTriggerBatches(TemporalWorkflowExecutor(env.client), task_queue=queue)
        trigger = uuid4()
        spec = BatchSpec(
            trigger_id=trigger,
            subscription_id=uuid4(),
            workspace_id="w",
            configured_by="u",
            window_seconds=60.0,
            max_events=10,
        )
        workflow_id = batch_workflow_id(trigger, None)
        async with Worker(
            env.client,
            task_queue=queue,
            workflows=[TriggerBatchWorkflow],
            activities=[fire, close],
            workflow_runner=create_workflow_runner(),
        ):
            first, second = uuid4(), uuid4()
            await batches.add(spec, first, workflow_id=workflow_id)
            await batches.add(spec, second, workflow_id=workflow_id)
            handle = env.client.get_workflow_handle(workflow_id)
            while (await handle.describe()).status == WorkflowExecutionStatus.RUNNING:
                await env.sleep(timedelta(seconds=61))
    assert fired == [[first, second]]
