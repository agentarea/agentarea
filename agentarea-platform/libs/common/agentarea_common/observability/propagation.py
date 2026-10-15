"""W3C trace context across the event broker (ADR-0043 §10).

Without an installed tracer provider the current span is invalid, so nothing is
injected and consumer spans are non-recording.
"""

from collections.abc import Iterator
from contextlib import contextmanager

from opentelemetry import trace
from opentelemetry.trace import Link, Span, SpanKind
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

_PROPAGATOR = TraceContextTextMapPropagator()
_TRACEPARENT = "traceparent"


def current_traceparent() -> str | None:
    """The active span as a W3C ``traceparent``, or None when no span is active."""
    carrier: dict[str, str] = {}
    _PROPAGATOR.inject(carrier)
    return carrier.get(_TRACEPARENT)


@contextmanager
def consumer_span(
    *,
    traceparent: str | None,
    destination: str,
    message_id: str,
    consumer_group: str | None = None,
    messaging_system: str = "redis",
) -> Iterator[Span]:
    """Run a message handler in a CONSUMER ``process`` span.

    The span continues the producer's trace and links to the producer span, so
    each fan-out consumer group shows up both under the trace and as a link.
    """
    producer_context = _PROPAGATOR.extract({_TRACEPARENT: traceparent}) if traceparent else None
    links: list[Link] = []
    if producer_context is not None:
        producer = trace.get_current_span(producer_context).get_span_context()
        if producer.is_valid:
            links.append(Link(producer))

    attributes = {
        "messaging.system": messaging_system,
        "messaging.destination.name": destination,
        "messaging.operation": "process",
        "messaging.operation.type": "process",
        "messaging.message.id": message_id,
    }
    if consumer_group is not None:
        attributes["messaging.consumer.group.name"] = consumer_group

    with trace.get_tracer(__name__).start_as_current_span(
        f"process {destination}",
        context=producer_context,
        kind=SpanKind.CONSUMER,
        links=links,
        attributes=attributes,
    ) as span:
        yield span
