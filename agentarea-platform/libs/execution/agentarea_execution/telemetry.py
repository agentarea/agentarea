"""Run, GenAI and tool instruments (ADR-0048 §9). No-ops until the process installs telemetry.

Every attribute value here comes from a closed set declared in this module, or
is a model spec or provider name: never an id, a tool name or a URL.
"""

from __future__ import annotations

import asyncio
import itertools
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from enum import StrEnum
from threading import Lock
from time import monotonic, perf_counter

import httpx
from opentelemetry import metrics
from opentelemetry.metrics import CallbackOptions, Observation
from opentelemetry.semconv._incubating.attributes.gen_ai_attributes import (
    GEN_AI_OPERATION_NAME,
    GEN_AI_PROVIDER_NAME,
    GEN_AI_REQUEST_MODEL,
    GEN_AI_TOKEN_TYPE,
    GenAiOperationNameValues,
    GenAiTokenTypeValues,
)
from opentelemetry.semconv._incubating.metrics.gen_ai_metrics import (
    GEN_AI_CLIENT_OPERATION_DURATION,
    GEN_AI_CLIENT_OPERATION_TIME_TO_FIRST_CHUNK,
    GEN_AI_CLIENT_TOKEN_USAGE,
)
from opentelemetry.semconv.attributes.error_attributes import ERROR_TYPE

from .llm_failures import classify_llm_failure

_meter = metrics.get_meter("agentarea.execution")


class RunFailureReason(StrEnum):
    NONE = "none"
    CANCELLED = "cancelled"
    LIMIT = "limit"
    POLICY = "policy"
    AGENT = "agent"
    INPUT_TIMEOUT = "input_timeout"
    PROVIDER = "provider"
    CONFIGURATION = "configuration"
    DEPENDENCY = "dependency"
    TIMEOUT = "timeout"
    INTERNAL = "internal"


_FAILURE_REASONS: dict[str, RunFailureReason] = {
    "cancelled": RunFailureReason.CANCELLED,
    "budget_exceeded": RunFailureReason.LIMIT,
    "token_limit": RunFailureReason.LIMIT,
    "tool_call_limit": RunFailureReason.LIMIT,
    "iteration_limit": RunFailureReason.LIMIT,
    "monthly_spend_cap_exceeded": RunFailureReason.LIMIT,
    "llm_run_cap_exceeded": RunFailureReason.LIMIT,
    "governance_denied": RunFailureReason.POLICY,
    "blocked": RunFailureReason.POLICY,
    "capability_unavailable": RunFailureReason.POLICY,
    "validation_failed": RunFailureReason.AGENT,
    "unmet_prerequisite": RunFailureReason.AGENT,
    "missing_final_response": RunFailureReason.AGENT,
    "task_unsuccessful": RunFailureReason.AGENT,
    "input_timeout": RunFailureReason.INPUT_TIMEOUT,
    "context_window_exceeded": RunFailureReason.PROVIDER,
    "provider_out_of_credits": RunFailureReason.PROVIDER,
    "provider_auth": RunFailureReason.PROVIDER,
    "rate_limited": RunFailureReason.PROVIDER,
    "model_deprecated": RunFailureReason.PROVIDER,
    "model_not_found": RunFailureReason.PROVIDER,
    "provider_content_policy": RunFailureReason.PROVIDER,
    "provider_bad_request": RunFailureReason.PROVIDER,
    "provider_unavailable": RunFailureReason.PROVIDER,
    "credentials_undecryptable": RunFailureReason.CONFIGURATION,
    "model_unpriced": RunFailureReason.CONFIGURATION,
    "policy_incomplete": RunFailureReason.CONFIGURATION,
    "usage_unavailable": RunFailureReason.PROVIDER,
    "pricing_unavailable": RunFailureReason.DEPENDENCY,
    "dependency_unavailable": RunFailureReason.DEPENDENCY,
    "timeout": RunFailureReason.TIMEOUT,
}

TERMINAL_RUN_STATUSES = frozenset({"completed", "failed", "cancelled", "blocked"})


def run_failure_reason(status: str, failure_reason: str | None) -> RunFailureReason:
    """The closed ``failure_reason`` a status update counts under.

    A run blocked by a policy carries the policy's own code, so any reason on a
    blocked run is a policy one; a code nobody mapped is internal.
    """
    if not failure_reason:
        if status == "failed":
            return RunFailureReason.INTERNAL
        if status == "cancelled":
            return RunFailureReason.CANCELLED
        if status == "blocked":
            return RunFailureReason.POLICY
        return RunFailureReason.NONE
    known = _FAILURE_REASONS.get(failure_reason)
    if known is not None:
        return known
    if status == "blocked":
        return RunFailureReason.POLICY
    return RunFailureReason.INTERNAL


_run_transitions = _meter.create_counter(
    "agentarea.run.transitions",
    unit="{transition}",
    description="Task status updates, by the status set and why a run stopped.",
)
_run_duration = _meter.create_histogram(
    "agentarea.run.duration",
    unit="s",
    description="Time from a run's start to a terminal status.",
)


def record_run_transition(
    status: str, failure_reason: str | None, run_started_at: datetime | None
) -> None:
    _run_transitions.add(
        1,
        {"status": status, "failure_reason": run_failure_reason(status, failure_reason).value},
    )
    if run_started_at is not None and status in TERMINAL_RUN_STATUSES:
        elapsed = datetime.now(UTC) - run_started_at
        _run_duration.record(max(elapsed.total_seconds(), 0.0), {"status": status})


OTHER_ERROR = "_OTHER"


def llm_error_type(error: BaseException) -> str:
    """``error.type`` of a failed model call: its classified cause, or ``_OTHER``."""
    if isinstance(error, asyncio.CancelledError):
        return "cancelled"
    failure = classify_llm_failure(error)
    return failure.cause if failure is not None else OTHER_ERROR


_llm_duration = _meter.create_histogram(
    GEN_AI_CLIENT_OPERATION_DURATION, unit="s", description="GenAI operation duration."
)
_llm_tokens = _meter.create_histogram(
    GEN_AI_CLIENT_TOKEN_USAGE, unit="{token}", description="Input and output tokens used."
)
_llm_first_chunk = _meter.create_histogram(
    GEN_AI_CLIENT_OPERATION_TIME_TO_FIRST_CHUNK,
    unit="s",
    description="Time to the first chunk of a streamed response.",
)
_llm_in_flight = _meter.create_up_down_counter(
    "agentarea.llm.in_flight", unit="{call}", description="Model calls in progress."
)


class LLMCall:
    def __init__(self, attributes: dict[str, str]) -> None:
        self._attributes = attributes
        self.started = perf_counter()
        self._first_chunk_seen = False
        self.outside_seconds = 0.0
        self.outside_error: BaseException | None = None

    @contextmanager
    def outside(self) -> Iterator[None]:
        """Our own work between chunks: not timed, and its failure is not the provider's."""
        started = perf_counter()
        try:
            yield
        except BaseException as error:
            self.outside_error = error
            raise
        finally:
            self.outside_seconds += perf_counter() - started

    def chunk(self) -> None:
        if not self._first_chunk_seen:
            self._first_chunk_seen = True
            _llm_first_chunk.record(perf_counter() - self.started, self._attributes)

    def usage(self, input_tokens: int, output_tokens: int) -> None:
        for token_type, count in (
            (GenAiTokenTypeValues.INPUT.value, input_tokens),
            (GenAiTokenTypeValues.OUTPUT.value, output_tokens),
        ):
            _llm_tokens.record(count, {**self._attributes, GEN_AI_TOKEN_TYPE: token_type})


class LLMPurpose(StrEnum):
    TURN = "turn"
    ANSWER_CHECK = "answer_check"
    COMPACTION = "compaction"


@contextmanager
def llm_call(provider: str, model: str, purpose: str) -> Iterator[LLMCall]:
    """Time one model call; ``model`` is the model spec's name, never a free-form id.

    A call our own work broke (``LLMCall.outside``) records no duration.
    """
    attributes = {
        GEN_AI_PROVIDER_NAME: provider,
        GEN_AI_REQUEST_MODEL: model,
        GEN_AI_OPERATION_NAME: GenAiOperationNameValues.CHAT.value,
        "agentarea.llm.purpose": LLMPurpose(purpose).value,
    }
    call = LLMCall(attributes)
    _llm_in_flight.add(1, attributes)
    failure: BaseException | None = None
    try:
        yield call
    except BaseException as error:
        failure = error
        raise
    finally:
        _llm_in_flight.add(-1, attributes)
        if failure is None or failure is not call.outside_error:
            _llm_duration.record(
                perf_counter() - call.started - call.outside_seconds,
                {**attributes, ERROR_TYPE: llm_error_type(failure)} if failure else attributes,
            )


class ToolKind(StrEnum):
    MCP = "mcp"
    BUILTIN = "builtin"
    OPENAPI = "openapi"
    PLATFORM = "platform"
    DELEGATION = "delegation"
    SKILL = "skill"


class ToolPath(StrEnum):
    WORKER = "worker"
    API = "api"


class ToolOutcome(StrEnum):
    OK = "ok"
    TOOL_ERROR = "tool_error"
    TRANSPORT_ERROR = "transport_error"
    TIMEOUT = "timeout"
    DENIED = "denied"
    HELD = "held"
    CANCELLED = "cancelled"


def tool_failure_outcome(error: BaseException) -> ToolOutcome:
    """The outcome of a tool call that raised instead of answering."""
    if isinstance(error, asyncio.CancelledError):
        return ToolOutcome.CANCELLED
    if isinstance(error, TimeoutError | httpx.TimeoutException):
        return ToolOutcome.TIMEOUT
    return ToolOutcome.TRANSPORT_ERROR


_tool_calls = _meter.create_counter(
    "agentarea.tool.calls", unit="{call}", description="Tool calls, by kind, path and outcome."
)
_tool_duration = _meter.create_histogram(
    "agentarea.tool.call.duration", unit="s", description="Tool call duration."
)
_tool_in_flight = _meter.create_up_down_counter(
    "agentarea.tool.in_flight", unit="{call}", description="Tool calls in progress."
)


class _InFlight:
    """Start times of the calls in progress, read from the exporter's thread."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._ids = itertools.count()
        self._started: dict[int, tuple[tuple[str, str], float]] = {}
        self._seen: set[tuple[str, str]] = set()

    def begin(self, key: tuple[str, str]) -> int:
        with self._lock:
            call_id = next(self._ids)
            self._started[call_id] = (key, monotonic())
            self._seen.add(key)
            return call_id

    def end(self, call_id: int) -> None:
        with self._lock:
            self._started.pop(call_id, None)

    def oldest(self) -> dict[tuple[str, str], float]:
        """Age of the oldest call per kind and path; 0 for one seen with none in progress."""
        now = monotonic()
        with self._lock:
            ages = dict.fromkeys(self._seen, 0.0)
            for key, started in self._started.values():
                ages[key] = max(ages[key], now - started)
        return ages


_tools_in_flight = _InFlight()


def _observe_oldest(_options: CallbackOptions) -> Iterable[Observation]:
    for (kind, path), age in _tools_in_flight.oldest().items():
        yield Observation(age, {"agentarea.tool.kind": kind, "path": path})


_meter.create_observable_gauge(
    "agentarea.tool.oldest_in_flight",
    callbacks=[_observe_oldest],
    unit="s",
    description="Age of the oldest tool call in progress in this process.",
)


class ToolCall:
    def __init__(self) -> None:
        self.outcome: ToolOutcome | None = None

    def failed(self, error: BaseException) -> None:
        """A call that raised and was answered as a failure instead."""
        self.outcome = tool_failure_outcome(error)

    def answered(self, success: bool) -> None:
        if self.outcome is None:
            self.outcome = ToolOutcome.OK if success else ToolOutcome.TOOL_ERROR


@contextmanager
def tool_call(kind: ToolKind, path: ToolPath) -> Iterator[ToolCall]:
    attributes = {"agentarea.tool.kind": kind.value, "path": path.value}
    call = ToolCall()
    call_id = _tools_in_flight.begin((kind.value, path.value))
    _tool_in_flight.add(1, attributes)
    started = perf_counter()
    try:
        yield call
    except BaseException as error:
        call.outcome = call.outcome or tool_failure_outcome(error)
        raise
    finally:
        _tools_in_flight.end(call_id)
        _tool_in_flight.add(-1, attributes)
        outcome = {**attributes, "outcome": (call.outcome or ToolOutcome.OK).value}
        _tool_calls.add(1, outcome)
        _tool_duration.record(perf_counter() - started, outcome)
