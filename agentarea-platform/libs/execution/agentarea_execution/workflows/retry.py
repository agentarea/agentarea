"""Temporal retry-policy factory.

Infrastructure adapter that translates the domain error taxonomy
(``agentarea_execution.exceptions.PermanentError``) into Temporal's
``RetryPolicy``. This is the only place that knows Temporal matches
``non_retryable_error_types`` by exception *class name*.

The non-retryable name set is derived from the ``PermanentError`` hierarchy, so
adding a new permanent error is a single edit in the domain (a new subclass) —
the policy picks it up with no change here. (Subclasses must be defined in /
imported via ``agentarea_execution.exceptions`` for the walk to see them; the
test suite guards that the known set is covered.)
"""

from datetime import timedelta

from agentarea_governance.domain.exceptions import EscalationRequiredError, GovernanceDeniedError
from temporalio.common import RetryPolicy

from agentarea_execution.exceptions import PermanentError

from .constants import (
    BOOKKEEPING_RETRY_ATTEMPTS,
    BOOKKEEPING_RETRY_MAX_INTERVAL,
    DEFAULT_RETRY_ATTEMPTS,
    LLM_RETRY_ATTEMPTS,
    LLM_RETRY_INITIAL_INTERVAL,
    LLM_RETRY_MAX_INTERVAL,
)

# A governance gate's verdict on the same call does not change between attempts;
# retrying only repeats it and delays the workflow from acting on it.
_GOVERNANCE_VERDICTS: tuple[type[Exception], ...] = (
    GovernanceDeniedError,
    EscalationRequiredError,
)


def _permanent_error_names() -> list[str]:
    """Collect class names of ``PermanentError`` and all its subclasses."""
    seen: set[str] = set()
    stack: list[type[BaseException]] = [PermanentError]
    while stack:
        cls = stack.pop()
        seen.add(cls.__name__)
        stack.extend(cls.__subclasses__())
    return sorted(seen)


# Computed once at import; exceptions module is fully imported by the time this
# runs, so every subclass defined there is registered.
NON_RETRYABLE_ERROR_TYPES: list[str] = sorted(
    {*_permanent_error_names(), *(cls.__name__ for cls in _GOVERNANCE_VERDICTS)}
)


def make_retry_policy(
    maximum_attempts: int = DEFAULT_RETRY_ATTEMPTS,
    *,
    initial_interval: timedelta = timedelta(seconds=1),
    maximum_interval: timedelta | None = None,
) -> RetryPolicy:
    """Build a RetryPolicy that never retries permanent failures.

    Activities that raise a ``PermanentError`` subclass cannot succeed on retry,
    so Temporal fails immediately instead of exhausting ``maximum_attempts``.
    Use this everywhere instead of constructing ``RetryPolicy`` directly so the
    non-retryable set stays consistent across activities. ``maximum_attempts=0``
    retries until the activity's schedule-to-close timeout.
    """
    return RetryPolicy(
        initial_interval=initial_interval,
        maximum_interval=maximum_interval,
        maximum_attempts=maximum_attempts,
        non_retryable_error_types=NON_RETRYABLE_ERROR_TYPES,
    )


def bookkeeping_retry_policy() -> RetryPolicy:
    """Idempotent status and spend bookkeeping: outlast a short outage."""
    return make_retry_policy(
        BOOKKEEPING_RETRY_ATTEMPTS, maximum_interval=BOOKKEEPING_RETRY_MAX_INTERVAL
    )


def model_call_retry_policy() -> RetryPolicy:
    """Model calls: back off through provider outages and rate limits."""
    return make_retry_policy(
        LLM_RETRY_ATTEMPTS,
        initial_interval=LLM_RETRY_INITIAL_INTERVAL,
        maximum_interval=LLM_RETRY_MAX_INTERVAL,
    )
