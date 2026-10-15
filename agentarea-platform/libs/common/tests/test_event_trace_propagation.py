"""W3C trace context crosses the event broker (ADR-0043 §10).

A publish injects the active span into ``IntegrationEvent.traceparent``; a
consumer runs its handler in a CONSUMER span that continues and links to the
producer's trace. With no tracer provider installed (OTel disabled) nothing is
injected and handlers run unchanged.
"""

from collections.abc import Iterator
from uuid import uuid4

import pytest
from agentarea_common.broker.interface import BrokerMessage
from agentarea_common.broker.topics import domain_events_topic
from agentarea_common.events.adapters.redis_streams import (
    RedisStreamsEventBus,
    decode,
    encode,
)
from agentarea_common.events.ports import IntegrationEvent
from agentarea_common.events.task_stream import publish_task_event, task_stream_name
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind
from opentelemetry.util._once import Once

_TYPE = "agentarea.test.v1.Traced"


class _FakeBroker:
    def __init__(self) -> None:
        self.submitted: list[tuple[str, dict[str, str]]] = []
        self.acked: list[str] = []

    async def submit(self, stream, fields, *, maxlen=None, ttl_seconds=None):
        self.submitted.append((stream, dict(fields)))
        return f"{len(self.submitted)}-0"

    async def ack(self, stream, group, message_id):
        self.acked.append(message_id)


def _install_provider(provider: TracerProvider | None) -> None:
    trace._TRACER_PROVIDER_SET_ONCE = Once()
    trace._TRACER_PROVIDER = None
    if provider is not None:
        trace.set_tracer_provider(provider)


@pytest.fixture
def exporter() -> Iterator[InMemorySpanExporter]:
    previous = trace._TRACER_PROVIDER
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    _install_provider(provider)
    yield exporter
    _install_provider(previous)


@pytest.fixture
def otel_disabled() -> Iterator[None]:
    previous = trace._TRACER_PROVIDER
    _install_provider(None)
    yield
    _install_provider(previous)


def _traceparent_trace_id(traceparent: str) -> int:
    return int(traceparent.split("-")[1], 16)


@pytest.mark.asyncio
async def test_publish_injects_active_span_into_traceparent(exporter):
    broker = _FakeBroker()
    bus = RedisStreamsEventBus(broker)
    tracer = trace.get_tracer("test")

    with tracer.start_as_current_span("request") as span:
        await bus.publish(IntegrationEvent(type=_TYPE, source="svc"))
        ctx = span.get_span_context()

    _, fields = broker.submitted[0]
    traceparent = fields["ce_traceparent"]
    assert traceparent == f"00-{ctx.trace_id:032x}-{ctx.span_id:016x}-{ctx.trace_flags:02x}"


@pytest.mark.asyncio
async def test_publish_keeps_an_explicit_traceparent(exporter):
    broker = _FakeBroker()
    bus = RedisStreamsEventBus(broker)
    explicit = f"00-{'a' * 32}-{'b' * 16}-01"

    with trace.get_tracer("test").start_as_current_span("request"):
        await bus.publish(IntegrationEvent(type=_TYPE, source="svc", traceparent=explicit))

    assert broker.submitted[0][1]["ce_traceparent"] == explicit


@pytest.mark.asyncio
async def test_handler_runs_in_consumer_span_linked_to_producer(exporter):
    broker = _FakeBroker()
    bus = RedisStreamsEventBus(broker)
    with trace.get_tracer("test").start_as_current_span("request") as producer_span:
        await bus.publish(IntegrationEvent(type=_TYPE, source="svc"))
        producer = producer_span.get_span_context()

    stream, fields = broker.submitted[0]
    seen: list[trace.SpanContext] = []

    async def handler(event: IntegrationEvent) -> None:
        seen.append(trace.get_current_span().get_span_context())

    await bus._handle(stream, "g1", BrokerMessage(id="1-0", fields=fields), handler)

    consumer = next(s for s in exporter.get_finished_spans() if s.kind == SpanKind.CONSUMER)
    assert consumer.name == f"process {stream}"
    assert seen[0].span_id == consumer.context.span_id
    assert consumer.context.trace_id == producer.trace_id
    assert consumer.parent is not None and consumer.parent.span_id == producer.span_id
    assert [(link.context.trace_id, link.context.span_id) for link in consumer.links] == [
        (producer.trace_id, producer.span_id)
    ]
    assert consumer.attributes["messaging.system"] == "redis"
    assert consumer.attributes["messaging.destination.name"] == stream
    assert consumer.attributes["messaging.operation"] == "process"
    assert consumer.attributes["messaging.consumer.group.name"] == "g1"
    assert consumer.attributes["messaging.message.id"] == "1-0"
    assert broker.acked == ["1-0"]


@pytest.mark.asyncio
async def test_failed_handler_records_error_and_is_not_acked(exporter):
    broker = _FakeBroker()
    bus = RedisStreamsEventBus(broker)
    fields = encode(IntegrationEvent(type=_TYPE, source="svc"))

    async def handler(event: IntegrationEvent) -> None:
        raise RuntimeError("boom")

    await bus._handle(
        domain_events_topic(_TYPE), "g1", BrokerMessage(id="1-0", fields=fields), handler
    )

    consumer = next(s for s in exporter.get_finished_spans() if s.kind == SpanKind.CONSUMER)
    assert consumer.status.status_code == trace.StatusCode.ERROR
    assert consumer.links == ()
    assert broker.acked == []


@pytest.mark.asyncio
async def test_task_stream_event_carries_active_traceparent(exporter):
    broker = _FakeBroker()
    task_id = str(uuid4())

    with trace.get_tracer("test").start_as_current_span("activity") as span:
        await publish_task_event(broker, task_id=task_id, event_type="task.started", data={})
        trace_id = span.get_span_context().trace_id

    stream, fields = broker.submitted[0]
    assert stream == f"tasks.events.{task_id}" == task_stream_name(task_id)
    assert _traceparent_trace_id(decode(fields).traceparent or "") == trace_id


@pytest.mark.asyncio
async def test_disabled_otel_injects_nothing_and_handlers_run(otel_disabled):
    broker = _FakeBroker()
    bus = RedisStreamsEventBus(broker)
    with trace.get_tracer("test").start_as_current_span("request"):
        await bus.publish(IntegrationEvent(type=_TYPE, source="svc"))

    stream, fields = broker.submitted[0]
    assert "ce_traceparent" not in fields

    handled: list[IntegrationEvent] = []

    async def handler(event: IntegrationEvent) -> None:
        handled.append(event)

    await bus._handle(stream, "g1", BrokerMessage(id="1-0", fields=fields), handler)
    assert len(handled) == 1
    assert broker.acked == ["1-0"]
