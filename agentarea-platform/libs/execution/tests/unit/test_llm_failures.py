"""A failed model call is reported by its cause, in words the workspace can act on."""

import httpx
import litellm
import pytest
from agentarea_agents_sdk.models.llm_model import LLMProviderHTTPError
from agentarea_execution.llm_failures import LLM_FAILURE_DETAIL, classify_llm_failure


def _wrapped(error: Exception, outer: str = "LLM call failed") -> RuntimeError:
    try:
        raise RuntimeError(outer) from error
    except RuntimeError as wrapper:
        return wrapper


@pytest.mark.parametrize(
    ("error", "cause", "says"),
    [
        (
            RuntimeError(
                "LLM usage accounting unavailable; token and cost policy cannot be enforced"
            ),
            "usage_unavailable",
            "did not report token usage",
        ),
        (
            RuntimeError(
                "LLM usage accounting unavailable: customer pricing failed: rates offline"
            ),
            "pricing_unavailable",
            "billing",
        ),
        (
            ValueError("Failed to decrypt secret. Key may have changed."),
            "credentials_undecryptable",
            "re-enter",
        ),
        (
            ValueError("model pricing is not configured; run budget cannot be enforced"),
            "model_unpriced",
            "no price",
        ),
        (
            litellm.BadRequestError(
                message='OpenrouterException - {"error":{"message":"Insufficient credits","code":402}}',
                model="m",
                llm_provider="openrouter",
            ),
            "provider_out_of_credits",
            "out of credits",
        ),
        (
            litellm.APIError(
                status_code=402, message="Payment required", llm_provider="x", model="m"
            ),
            "provider_out_of_credits",
            "out of credits",
        ),
        (
            LLMProviderHTTPError(402, "This request requires more credits"),
            "provider_out_of_credits",
            "out of credits",
        ),
        (
            litellm.AuthenticationError(
                message="Incorrect API key", llm_provider="openai", model="m"
            ),
            "provider_auth",
            "api key",
        ),
        (
            litellm.RateLimitError(message="Too many requests", llm_provider="openai", model="m"),
            "rate_limited",
            "try again",
        ),
        (
            litellm.NotFoundError(
                message="model gpt-9 not found", llm_provider="openai", model="m"
            ),
            "model_not_found",
            "not found",
        ),
        (
            litellm.ContextWindowExceededError(
                message="maximum context length is 8192 tokens", model="m", llm_provider="openai"
            ),
            "context_window_exceeded",
            "context window",
        ),
        (
            litellm.Timeout(message="Request timed out", model="m", llm_provider="openai"),
            "timeout",
            "timed out",
        ),
        (
            litellm.ServiceUnavailableError(message="overloaded", llm_provider="x", model="m"),
            "provider_unavailable",
            "unavailable",
        ),
    ],
    ids=[
        "no_usage",
        "customer_pricing",
        "decrypt",
        "unpriced",
        "credits_in_400_body",
        "status_402",
        "direct_stream_402",
        "auth",
        "rate_limit",
        "not_found",
        "context_window",
        "timeout",
        "unavailable",
    ],
)
def test_known_causes_have_their_own_message(error: Exception, cause: str, says: str):
    failure = classify_llm_failure(error)

    assert failure is not None
    assert failure.cause == cause
    assert says in failure.message.lower()
    assert "Failed to get a response" not in failure.message


def test_a_provider_400_carries_the_providers_own_words():
    error = litellm.BadRequestError(
        message='OpenAIException - {"error":{"message":"Invalid value for \'tools[0].name\'","type":"invalid_request_error"}}',
        model="m",
        llm_provider="openai",
    )

    failure = classify_llm_failure(error)

    assert failure is not None
    assert failure.cause == "provider_bad_request"
    assert "Invalid value for 'tools[0].name'" in failure.message
    assert "OpenAIException" not in failure.message


def test_a_direct_stream_400_carries_the_body_message():
    failure = classify_llm_failure(LLMProviderHTTPError(400, "max_tokens is too large"))

    assert failure is not None
    assert failure.cause == "provider_bad_request"
    assert "max_tokens is too large" in failure.message


def test_the_cause_is_found_through_a_wrapping_exception():
    failure = classify_llm_failure(
        _wrapped(litellm.AuthenticationError(message="bad key", llm_provider="x", model="m"))
    )

    assert failure is not None
    assert failure.cause == "provider_auth"


def test_an_httpx_status_error_reads_its_status():
    request = httpx.Request("POST", "https://gateway.example/v1/chat/completions")
    response = httpx.Response(402, request=request)
    error = httpx.HTTPStatusError("Client error", request=request, response=response)

    failure = classify_llm_failure(error)

    assert failure is not None
    assert failure.cause == "provider_out_of_credits"


def test_a_rate_limit_that_mentions_quota_is_still_a_rate_limit():
    error = litellm.RateLimitError(
        message="Quota exceeded for metric: requests per minute", llm_provider="gemini", model="m"
    )

    failure = classify_llm_failure(error)

    assert failure is not None
    assert failure.cause == "rate_limited"
    assert failure.retryable


def test_an_unknown_error_is_not_classified():
    assert classify_llm_failure(RuntimeError("something odd")) is None


def test_permanent_causes_are_not_retryable():
    for error in (
        ValueError("Failed to decrypt secret. Key may have changed."),
        LLMProviderHTTPError(400, "bad"),
        LLMProviderHTTPError(402, "no credits"),
    ):
        failure = classify_llm_failure(error)
        assert failure is not None
        assert not failure.retryable


def test_the_detail_round_trips_as_plain_data():
    failure = classify_llm_failure(LLMProviderHTTPError(401, "invalid key"))

    assert failure is not None
    detail = failure.as_detail()
    assert detail[LLM_FAILURE_DETAIL]["cause"] == "provider_auth"
    assert detail[LLM_FAILURE_DETAIL]["message"] == failure.message
