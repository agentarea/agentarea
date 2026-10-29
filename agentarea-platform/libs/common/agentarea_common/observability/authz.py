"""Time spent answering authorization questions (``agentarea.authz.duration``)."""

from collections.abc import Iterator
from contextlib import contextmanager
from time import perf_counter

from opentelemetry import metrics

_DURATION = metrics.get_meter("agentarea.authz").create_histogram(
    "agentarea.authz.duration",
    unit="s",
    description="Time spent answering authorization questions, by operation.",
)


@contextmanager
def authz_timed(operation: str) -> Iterator[None]:
    started = perf_counter()
    try:
        yield
    finally:
        _DURATION.record(perf_counter() - started, {"operation": operation})
