"""Which firing failures repeat on every retry, and which are worth retrying the event for.

A permanent failure -- a condition that cannot be decided, an agent with no
model, a refused task -- is reported as the firing's outcome. Infrastructure
trouble (a database blip, Temporal or the model provider unavailable) is
transient even when it surfaces wrapped in one of those errors; it, and any
failure nobody classified, is retried.
"""

import sys
from collections.abc import Iterator

import httpx
import redis.exceptions
from agentarea_common.rebac import OpenFGAUnavailableError
from agentarea_llm.infrastructure.model_clients import ModelProviderUnavailableError
from sqlalchemy import exc as sa_exc
from temporalio.service import RPCError, RPCStatusCode


class TaskNotStartedError(RuntimeError):
    """The task was stored but its workflow did not start; the stored task starts on retry."""


_TRANSIENT_TYPES: tuple[type[BaseException], ...] = (
    TaskNotStartedError,
    ModelProviderUnavailableError,
    ConnectionError,
    TimeoutError,
    sa_exc.OperationalError,
    sa_exc.InterfaceError,
    sa_exc.TimeoutError,
    httpx.TransportError,
    redis.exceptions.ConnectionError,
    redis.exceptions.TimeoutError,
    OpenFGAUnavailableError,
)
_TRANSIENT_RPC_STATUSES = frozenset(
    {
        RPCStatusCode.UNAVAILABLE,
        RPCStatusCode.DEADLINE_EXCEEDED,
        RPCStatusCode.RESOURCE_EXHAUSTED,
        RPCStatusCode.ABORTED,
    }
)
# SQLSTATE classes: 08 connection exception, 40 transaction rollback (deadlock,
# serialization failure), 53 insufficient resources, 57P operator intervention.
_TRANSIENT_SQLSTATE_PREFIXES = ("08", "40", "53", "57P")
_LITELLM_TRANSIENT_NAMES = (
    "APIConnectionError",
    "Timeout",
    "RateLimitError",
    "ServiceUnavailableError",
    "InternalServerError",
    "BadGatewayError",
)


def _chain(error: BaseException) -> Iterator[BaseException]:
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def _sqlstate(error: sa_exc.DBAPIError) -> str | None:
    original = error.orig
    code = getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)
    return str(code) if code else None


def _litellm_transient_types() -> tuple[type[BaseException], ...]:
    # A litellm exception can only be in the chain once litellm is loaded;
    # looking it up this way keeps the trigger library from importing it.
    module = sys.modules.get("litellm.exceptions")
    if module is None:
        return ()
    return tuple(getattr(module, name) for name in _LITELLM_TRANSIENT_NAMES)


def _permanent_types() -> tuple[type[BaseException], ...]:
    from agentarea_llm.application.model_service import ModelUnavailableError
    from agentarea_tasks.domain.exceptions import (
        AgentModelNotConfiguredError,
        BudgetCapExceededError,
        SchedulingNotSupportedError,
    )

    from .llm_condition_evaluator import LLMConditionEvaluationError
    from .logging_utils import TriggerConditionError, TriggerValidationError

    return (
        TriggerConditionError,
        TriggerValidationError,
        LLMConditionEvaluationError,
        ModelUnavailableError,
        AgentModelNotConfiguredError,
        BudgetCapExceededError,
        SchedulingNotSupportedError,
        PermissionError,
        ValueError,
    )


def is_permanent(error: BaseException) -> bool:
    """Whether ``error`` would fail the same way on a retry of the same event."""
    return not is_transient(error) and isinstance(error, _permanent_types())


def is_transient(error: BaseException) -> bool:
    """Whether ``error``, or anything that caused it, is infrastructure that may recover."""
    litellm_types = _litellm_transient_types()
    for link in _chain(error):
        if isinstance(link, _TRANSIENT_TYPES + litellm_types):
            return True
        if isinstance(link, RPCError) and link.status in _TRANSIENT_RPC_STATUSES:
            return True
        if isinstance(link, sa_exc.DBAPIError):
            if link.connection_invalidated:
                return True
            sqlstate = _sqlstate(link)
            if sqlstate and sqlstate.startswith(_TRANSIENT_SQLSTATE_PREFIXES):
                return True
    return False
