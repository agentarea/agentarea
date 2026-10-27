"""With tracing on, a Temporal worker still starts and runs workflows and activities."""

import uuid
from datetime import timedelta

from temporalio import activity, workflow

with workflow.unsafe.imports_passed_through():
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from temporalio.client import Client
    from temporalio.testing import WorkflowEnvironment
    from temporalio.worker import Worker

    from agentarea_common.config import ObservabilitySettings
    from agentarea_common.observability import get_temporal_plugins
    from agentarea_common.workflow.sandbox import create_workflow_runner


@activity.defn
async def traced_echo(value: str) -> str:
    span = trace.get_tracer(__name__).start_span("echo")
    span.end()
    return value


@workflow.defn
class TracedEchoWorkflow:
    @workflow.run
    async def run(self, value: str) -> str:
        return await workflow.execute_activity(
            traced_echo, value, start_to_close_timeout=timedelta(seconds=10)
        )


async def test_a_worker_with_tracing_on_runs_a_workflow_and_its_activity():
    # What setup_otel installs in a worker process: an ordinary SDK provider.
    if not isinstance(trace.get_tracer_provider(), TracerProvider):
        trace.set_tracer_provider(TracerProvider())
    plugins = get_temporal_plugins(ObservabilitySettings(ENABLED=True))
    assert plugins

    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = await Client.connect(
            env.client.service_client.config.target_host,
            namespace=env.client.namespace,
            plugins=plugins,
        )
        task_queue = f"otel-{uuid.uuid4()}"
        async with Worker(
            client,
            task_queue=task_queue,
            workflows=[TracedEchoWorkflow],
            activities=[traced_echo],
            workflow_runner=create_workflow_runner(),
        ):
            result = await client.execute_workflow(
                TracedEchoWorkflow.run, "ok", id=f"otel-{uuid.uuid4()}", task_queue=task_queue
            )

    assert result == "ok"
