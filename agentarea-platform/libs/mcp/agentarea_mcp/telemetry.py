"""MCP client instruments (ADR-0048 §9). No-ops until the process installs telemetry."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from time import perf_counter
from typing import Any

from mcp import MCPError
from opentelemetry import metrics
from opentelemetry.semconv._incubating.attributes.mcp_attributes import MCP_METHOD_NAME
from opentelemetry.semconv._incubating.metrics.mcp_metrics import MCP_CLIENT_OPERATION_DURATION
from opentelemetry.semconv.attributes.error_attributes import ERROR_TYPE

TOOL_ERROR = "tool_error"

_meter = metrics.get_meter("agentarea.mcp")

dispatch_stamp_dropped = _meter.create_counter(
    "agentarea.mcp.dispatch_stamp.dropped",
    unit="{stamp}",
    description="last_dispatch stamps dropped because the write queue was full.",
)
era_renegotiated = _meter.create_counter(
    "agentarea.mcp.client.era_renegotiated",
    unit="{connection}",
    description="Connections opened from a cached protocol era that the server refused.",
)
_operation_duration = _meter.create_histogram(
    MCP_CLIENT_OPERATION_DURATION,
    unit="s",
    description="Duration of an MCP request as the client sees it.",
)


def mcp_error_type(error: BaseException) -> str:
    """``error.type`` of a failed request: the JSON-RPC code, else the exception's class."""
    if isinstance(error, MCPError):
        return str(error.code)
    return type(error).__qualname__


class Operation:
    def __init__(self) -> None:
        self.error_type: str | None = None

    def result(self, result: Any) -> Any:
        """Note a tool result that reports an error, and pass the result on."""
        if getattr(result, "is_error", False):
            self.error_type = TOOL_ERROR
        return result


@contextmanager
def mcp_operation(method: str) -> Iterator[Operation]:
    operation = Operation()
    started = perf_counter()
    try:
        yield operation
    except BaseException as error:
        operation.error_type = mcp_error_type(error)
        raise
    finally:
        attributes = {MCP_METHOD_NAME: method}
        if operation.error_type is not None:
            attributes[ERROR_TYPE] = operation.error_type
        _operation_duration.record(perf_counter() - started, attributes)
