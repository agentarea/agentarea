"""Tests for the permanent-error taxonomy and Temporal retry-policy factory.

Guards the contract that every permanent (non-retryable) domain error is wired
into the workflow's RetryPolicy, so a missing agent/model fails fast instead of
exhausting the retry budget.
"""

from agentarea_execution.activities.event_publisher import _is_non_retryable_error
from agentarea_execution.exceptions import (
    AgentNotFoundError,
    ModelInstanceNotFoundError,
    PermanentError,
)
from agentarea_execution.workflows.constants import (
    DEFAULT_RETRY_ATTEMPTS,
    LLM_RETRY_ATTEMPTS,
)
from agentarea_execution.workflows.retry import (
    NON_RETRYABLE_ERROR_TYPES,
    make_retry_policy,
)


def _all_permanent_subclasses() -> set[str]:
    seen: set[str] = set()
    stack: list[type] = [PermanentError]
    while stack:
        cls = stack.pop()
        seen.add(cls.__name__)
        stack.extend(cls.__subclasses__())
    return seen


def test_concrete_errors_are_permanent():
    assert issubclass(AgentNotFoundError, PermanentError)
    assert issubclass(ModelInstanceNotFoundError, PermanentError)


def test_non_retryable_set_covers_whole_hierarchy():
    """Adding a PermanentError subclass without it appearing here is the bug
    this guards against."""
    assert _all_permanent_subclasses() <= set(NON_RETRYABLE_ERROR_TYPES)


def test_known_errors_are_non_retryable():
    assert "AgentNotFoundError" in NON_RETRYABLE_ERROR_TYPES
    assert "ModelInstanceNotFoundError" in NON_RETRYABLE_ERROR_TYPES


def test_make_retry_policy_wires_non_retryable_types():
    policy = make_retry_policy()
    assert policy.maximum_attempts == DEFAULT_RETRY_ATTEMPTS
    assert policy.non_retryable_error_types == NON_RETRYABLE_ERROR_TYPES


def test_make_retry_policy_respects_custom_attempts():
    assert make_retry_policy(2).maximum_attempts == 2


def test_llm_calls_retry_transient_failures():
    """LLM calls must allow more than one attempt, else no transient failure
    (rate limit, network) is ever retried regardless of classification."""
    assert LLM_RETRY_ATTEMPTS > 1


def test_rate_limit_is_retryable_even_when_message_says_exceeded():
    """A 429 'rate limit exceeded' must retry — the quota check's broad
    'exceeded' match must not swallow it into fail-fast."""
    assert _is_non_retryable_error(Exception("429 Rate limit exceeded, retry")) is False
    assert _is_non_retryable_error(Exception("Too Many Requests")) is False


def test_transient_errors_are_retryable():
    assert _is_non_retryable_error(TimeoutError("request timeout")) is False
    assert _is_non_retryable_error(ConnectionError("connection reset")) is False
    assert _is_non_retryable_error(Exception("503 service unavailable")) is False


def test_permanent_llm_errors_fail_fast():
    assert _is_non_retryable_error(Exception("401 unauthorized: invalid api key")) is True
    assert _is_non_retryable_error(Exception("insufficient balance, please recharge")) is True
    assert _is_non_retryable_error(Exception("model gpt-x does not exist")) is True
