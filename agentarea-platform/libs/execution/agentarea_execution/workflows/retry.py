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

from temporalio.common import RetryPolicy

from agentarea_execution.exceptions import PermanentError

from .constants import DEFAULT_RETRY_ATTEMPTS


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
NON_RETRYABLE_ERROR_TYPES: list[str] = _permanent_error_names()


def make_retry_policy(maximum_attempts: int = DEFAULT_RETRY_ATTEMPTS) -> RetryPolicy:
    """Build a RetryPolicy that never retries permanent failures.

    Activities that raise a ``PermanentError`` subclass cannot succeed on retry,
    so Temporal fails immediately instead of exhausting ``maximum_attempts``.
    Use this everywhere instead of constructing ``RetryPolicy`` directly so the
    non-retryable set stays consistent across activities.
    """
    return RetryPolicy(
        maximum_attempts=maximum_attempts,
        non_retryable_error_types=NON_RETRYABLE_ERROR_TYPES,
    )
