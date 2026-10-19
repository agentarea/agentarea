"""A batch fires once, on its timer or its count, with each event once; cancelled, it closes."""

import uuid
from datetime import timedelta
from uuid import UUID, uuid4

from agentarea_common.workflow.sandbox import create_workflow_runner
from agentarea_execution.workflows.trigger_batch_workflow import (
    ADD_EVENT_SIGNAL,
    CANCELLED_REASON,
    CLOSE_TRIGGER_BATCH,
    FIRE_TRIGGER_BATCH,
    BatchSpec,
    OpenBatch,
    TriggerBatchWorkflow,
)
from temporalio import activity
from temporalio.client import Client, WorkflowExecutionStatus
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker


def _spec(**kw) -> BatchSpec:
    return BatchSpec(
        trigger_id=uuid4(),
        subscription_id=uuid4(),
        workspace_id="w",
        configured_by="u",
        **{"window_seconds": 60.0, "max_events": 3, **kw},
    )


class _Activities:
    def __init__(self, env: WorkflowEnvironment):
        self.env = env
        self.fired: list[tuple[list[UUID], float]] = []
        self.closed: list[OpenBatch] = []

    def all(self):
        @activity.defn(name=FIRE_TRIGGER_BATCH)
        async def fire(batch: OpenBatch) -> int:
            now = (await self.env.get_current_time()).timestamp()
            self.fired.append((batch.event_ids, now))
            return len(batch.event_ids)

        @activity.defn(name=CLOSE_TRIGGER_BATCH)
        async def close(batch: OpenBatch) -> int:
            self.closed.append(batch)
            return len(batch.event_ids)

        return [fire, close]


async def _env_and_client():
    env = await WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter)
    return env, env.client


async def _signal_with_start(client: Client, spec: BatchSpec, workflow_id: str, event: UUID, queue):
    return await client.start_workflow(
        TriggerBatchWorkflow.run,
        spec,
        id=workflow_id,
        task_queue=queue,
        start_signal=ADD_EVENT_SIGNAL,
        start_signal_args=[event],
    )


async def test_two_events_fire_once_when_the_window_has_passed():
    env, client = await _env_and_client()
    async with env:
        acts = _Activities(env)
        queue = str(uuid.uuid4())
        async with Worker(
            client,
            task_queue=queue,
            workflows=[TriggerBatchWorkflow],
            activities=acts.all(),
            workflow_runner=create_workflow_runner(),
        ):
            first, second = uuid4(), uuid4()
            opened = (await env.get_current_time()).timestamp()
            spec = _spec()
            handle = await _signal_with_start(client, spec, "b1", first, queue)
            await _signal_with_start(client, spec, "b1", second, queue)
            assert await handle.result() == 2
    ((ids, at),) = acts.fired
    assert ids == [first, second]
    assert at - opened >= 60


async def test_the_count_fires_before_the_timer():
    env, client = await _env_and_client()
    async with env:
        acts = _Activities(env)
        queue = str(uuid.uuid4())
        async with Worker(
            client,
            task_queue=queue,
            workflows=[TriggerBatchWorkflow],
            activities=acts.all(),
            workflow_runner=create_workflow_runner(),
        ):
            events = [uuid4(), uuid4(), uuid4()]
            spec = _spec(window_seconds=3600.0)
            opened = (await env.get_current_time()).timestamp()
            handle = None
            for event in events:
                handle = await _signal_with_start(client, spec, "b2", event, queue)
            assert handle is not None
            assert await handle.result() == 3
    ((ids, at),) = acts.fired
    assert ids == events
    assert at - opened < 3600


async def test_a_redelivered_event_joins_the_batch_once():
    env, client = await _env_and_client()
    async with env:
        acts = _Activities(env)
        queue = str(uuid.uuid4())
        async with Worker(
            client,
            task_queue=queue,
            workflows=[TriggerBatchWorkflow],
            activities=acts.all(),
            workflow_runner=create_workflow_runner(),
        ):
            event = uuid4()
            spec = _spec()
            handle = await _signal_with_start(client, spec, "b3", event, queue)
            await _signal_with_start(client, spec, "b3", event, queue)
            await handle.signal(ADD_EVENT_SIGNAL, event)
            assert await handle.result() == 1
    assert [ids for ids, _ in acts.fired] == [[event]]


async def test_a_full_batch_fires_and_the_rest_opens_the_next_run():
    env, client = await _env_and_client()
    async with env:
        acts = _Activities(env)
        queue = str(uuid.uuid4())
        async with Worker(
            client,
            task_queue=queue,
            workflows=[TriggerBatchWorkflow],
            activities=acts.all(),
            workflow_runner=create_workflow_runner(),
        ):
            spec = _spec(max_events=2, window_seconds=30.0)
            handle = await client.start_workflow(
                TriggerBatchWorkflow.run, spec, id="b4", task_queue=queue
            )
            events = [uuid4() for _ in range(5)]
            for event in events:
                await handle.signal(ADD_EVENT_SIGNAL, event)
            latest = client.get_workflow_handle("b4")
            while (await latest.describe()).status == WorkflowExecutionStatus.RUNNING:
                await env.sleep(timedelta(seconds=31))
    fired = [ids for ids, _ in acts.fired]
    assert [e for ids in fired for e in ids] == events
    assert all(len(ids) <= 2 for ids in fired)


async def test_a_cancelled_batch_closes_its_events_without_firing():
    env, client = await _env_and_client()
    async with env:
        acts = _Activities(env)
        queue = str(uuid.uuid4())
        async with Worker(
            client,
            task_queue=queue,
            workflows=[TriggerBatchWorkflow],
            activities=acts.all(),
            workflow_runner=create_workflow_runner(),
        ):
            first, second = uuid4(), uuid4()
            spec = _spec()
            handle = await _signal_with_start(client, spec, "b5", first, queue)
            await _signal_with_start(client, spec, "b5", second, queue)
            await handle.cancel()
            assert await handle.result() == 0
    assert acts.fired == []
    (closed,) = acts.closed
    assert closed.event_ids == [first, second]
    assert closed.reason == CANCELLED_REASON
    assert closed.workflow_id == "b5"
