"""Domain error taxonomy for agent execution.

``PermanentError`` marks a failure that can never succeed by retrying: the
input is wrong, not the moment (a missing agent, a missing model instance,
invalid configuration). This is a domain classification — "permanent vs
transient" is part of the ubiquitous language — so it lives in the domain and
knows nothing about Temporal or any transport.

The infrastructure layer (``workflows/retry.py``) translates this taxonomy into
Temporal's ``RetryPolicy.non_retryable_error_types``. Keep concrete permanent
failures as subclasses of ``PermanentError`` and the retry policy picks them up
automatically.
"""

from __future__ import annotations


class PermanentError(Exception):
    """Base class for failures that must not be retried."""


class AgentNotFoundError(PermanentError):
    """The requested agent does not exist (neither tenant row nor catalog)."""


class ModelInstanceNotFoundError(PermanentError):
    """The requested model instance does not exist."""


class NoModelBoundError(PermanentError):
    """The agent has no model bound and the run supplied no override."""
