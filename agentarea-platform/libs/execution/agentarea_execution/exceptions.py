"""Exceptions for agent execution activities.

``NonRetryableActivityError`` and its subclasses mark failures that are
permanent: the workflow can never succeed by retrying the activity (a missing
agent, a missing model instance, invalid configuration, ...). The workflow
passes ``NON_RETRYABLE_ERROR_TYPES`` to every activity's
``RetryPolicy.non_retryable_error_types`` so Temporal fails fast instead of
burning the whole retry budget on an error that will recur identically.

Temporal matches ``non_retryable_error_types`` against the raised exception's
class name, not its base classes, so every concrete type must be listed in
``NON_RETRYABLE_ERROR_TYPES`` explicitly.
"""

from __future__ import annotations


class NonRetryableActivityError(Exception):
    """Base class for activity failures that must not be retried."""


class AgentNotFoundError(NonRetryableActivityError):
    """The requested agent does not exist (neither tenant row nor catalog)."""


class ModelInstanceNotFoundError(NonRetryableActivityError):
    """The requested model instance does not exist."""


# Exception class names that must never be retried. Kept in sync with the
# concrete subclasses above — Temporal matches on the concrete class name, so
# listing only the base class would not catch the subclasses.
NON_RETRYABLE_ERROR_TYPES: list[str] = [
    NonRetryableActivityError.__name__,
    AgentNotFoundError.__name__,
    ModelInstanceNotFoundError.__name__,
]
