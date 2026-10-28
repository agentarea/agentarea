"""A failed model call is reported by its cause, in words the workspace can act on."""

import httpx
import pytest
from agentarea_agents_sdk.models.llm_model import LLMProviderHTTPError
from agentarea_common.utils.url_safety import UnsafeUrlError
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
            LLMProviderHTTPError(400, "Insufficient credits"),
            "provider_out_of_credits",
            "out of credits",
        ),
        (
            LLMProviderHTTPError(400, '{"error":{"code":402}}'),
            "provider_out_of_credits",
            "out of credits",
        ),
        (
            LLMProviderHTTPError(402, "This request requires more credits"),
            "provider_out_of_credits",
            "out of credits",
        ),
        (
            LLMProviderHTTPError(400, "Quota exceeded for this project"),
            "provider_out_of_credits",
            "out of credits",
        ),
        (
            LLMProviderHTTPError(401, "Incorrect API key provided"),
            "provider_auth",
            "api key",
        ),
        (
            LLMProviderHTTPError(403, "Your organization does not have access to this model"),
            "provider_auth",
            "api key",
        ),
        (
            LLMProviderHTTPError(429, "Too many requests"),
            "rate_limited",
            "try again",
        ),
        (
            LLMProviderHTTPError(404, "The model `gpt-9` does not exist"),
            "model_not_found",
            "not found",
        ),
        (
            LLMProviderHTTPError(404, "The model `gpt-3` has been deprecated"),
            "model_deprecated",
            "deprecated",
        ),
        (
            LLMProviderHTTPError(
                400,
                "This model's maximum context length is 8192 tokens. However, you requested 9000",
            ),
            "context_window_exceeded",
            "context window",
        ),
        (
            LLMProviderHTTPError(400, "prompt is too long: 210000 tokens > 200000 maximum"),
            "context_window_exceeded",
            "context window",
        ),
        (
            LLMProviderHTTPError(413, "Input is too long for requested model."),
            "context_window_exceeded",
            "context window",
        ),
        (
            LLMProviderHTTPError(
                422, "The input or output tokens must be reduced: too many tokens"
            ),
            "context_window_exceeded",
            "context window",
        ),
        (
            LLMProviderHTTPError(
                400, "Your request was rejected as a result of our safety system."
            ),
            "provider_content_policy",
            "content policy",
        ),
        (
            httpx.ConnectTimeout(""),
            "timeout",
            "timed out",
        ),
        (
            httpx.ReadTimeout("read operation"),
            "timeout",
            "timed out",
        ),
        (
            TimeoutError(),
            "timeout",
            "timed out",
        ),
        (
            LLMProviderHTTPError(408, "Request Timeout"),
            "timeout",
            "timed out",
        ),
        (
            LLMProviderHTTPError(503, "Service Unavailable"),
            "provider_unavailable",
            "unavailable",
        ),
        (
            LLMProviderHTTPError(529, "Overloaded"),
            "provider_unavailable",
            "unavailable",
        ),
        (
            LLMProviderHTTPError(500, "Internal server error"),
            "provider_unavailable",
            "unavailable",
        ),
        (
            httpx.ConnectError("[Errno 111] Connection refused"),
            "provider_unavailable",
            "unavailable",
        ),
        (
            httpx.RemoteProtocolError("peer closed connection without sending complete message"),
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
        "code_402_in_400_body",
        "status_402",
        "quota_exceeded",
        "auth_401",
        "auth_403",
        "rate_limit",
        "not_found",
        "deprecated",
        "context_window_openai",
        "context_window_anthropic",
        "context_window_413",
        "context_window_422",
        "content_policy",
        "connect_timeout",
        "read_timeout",
        "builtin_timeout",
        "status_408",
        "status_503",
        "anthropic_overloaded_529",
        "status_500",
        "connect_error",
        "transport_error",
    ],
)
def test_known_causes_have_their_own_message(error: Exception, cause: str, says: str):
    failure = classify_llm_failure(error)

    assert failure is not None
    assert failure.cause == cause
    assert says in failure.message.lower()
    assert "Failed to get a response" not in failure.message


def test_a_provider_400_carries_the_providers_own_words():
    failure = classify_llm_failure(LLMProviderHTTPError(400, "Invalid value for 'tools[0].name'"))

    assert failure is not None
    assert failure.cause == "provider_bad_request"
    assert failure.message.endswith("Invalid value for 'tools[0].name'")
    assert "HTTP 400" not in failure.message


def test_a_direct_stream_400_carries_the_body_message():
    failure = classify_llm_failure(LLMProviderHTTPError(400, "max_tokens is too large"))

    assert failure is not None
    assert failure.cause == "provider_bad_request"
    assert "max_tokens is too large" in failure.message


@pytest.mark.parametrize("status", [409, 413, 415, 422])
def test_any_other_client_error_is_a_bad_request(status: int):
    failure = classify_llm_failure(LLMProviderHTTPError(status, "Request entity rejected"))

    assert failure is not None
    assert failure.cause == "provider_bad_request"
    assert not failure.retryable


def test_a_context_phrase_on_a_rate_limit_is_still_a_rate_limit():
    failure = classify_llm_failure(LLMProviderHTTPError(429, "too many tokens per minute"))

    assert failure is not None
    assert failure.cause == "rate_limited"


def test_the_cause_is_found_through_a_wrapping_exception():
    failure = classify_llm_failure(_wrapped(LLMProviderHTTPError(401, "bad key")))

    assert failure is not None
    assert failure.cause == "provider_auth"


def test_a_wrapped_transport_error_is_unavailable():
    failure = classify_llm_failure(_wrapped(httpx.ConnectError("connection refused")))

    assert failure is not None
    assert failure.cause == "provider_unavailable"
    assert failure.retryable


def test_a_body_echoed_in_an_error_reduces_to_the_providers_sentence():
    request = httpx.Request("POST", "https://gateway.example/v1/chat/completions")
    response = httpx.Response(400, request=request)
    error = httpx.HTTPStatusError(
        'HTTPStatusError: {"error":{"message":"Unknown parameter: \'foo\'"}}',
        request=request,
        response=response,
    )

    failure = classify_llm_failure(_wrapped(error))

    assert failure is not None
    assert failure.cause == "provider_bad_request"
    assert failure.message.endswith("Unknown parameter: 'foo'")


def test_an_httpx_status_error_reads_its_status():
    request = httpx.Request("POST", "https://gateway.example/v1/chat/completions")
    response = httpx.Response(402, request=request)
    error = httpx.HTTPStatusError("Client error", request=request, response=response)

    failure = classify_llm_failure(error)

    assert failure is not None
    assert failure.cause == "provider_out_of_credits"


def test_a_rate_limit_that_mentions_quota_is_still_a_rate_limit():
    error = LLMProviderHTTPError(429, "Quota exceeded for metric: requests per minute")

    failure = classify_llm_failure(error)

    assert failure is not None
    assert failure.cause == "rate_limited"
    assert failure.retryable


@pytest.mark.parametrize(
    "error",
    [
        RuntimeError("something odd"),
        UnsafeUrlError("the endpoint URL points to an address this deployment does not call"),
        ValueError("No base URL configured for direct HTTP completion call"),
    ],
    ids=["unknown", "refused_endpoint", "no_address"],
)
def test_an_error_that_is_not_a_provider_answer_is_not_classified(error: Exception):
    assert classify_llm_failure(error) is None


def test_permanent_causes_are_not_retryable():
    for error in (
        ValueError("Failed to decrypt secret. Key may have changed."),
        LLMProviderHTTPError(400, "bad"),
        LLMProviderHTTPError(401, "invalid key"),
        LLMProviderHTTPError(402, "no credits"),
        LLMProviderHTTPError(404, "no such model"),
        LLMProviderHTTPError(400, "prompt is too long"),
    ):
        failure = classify_llm_failure(error)
        assert failure is not None
        assert not failure.retryable


def test_transient_causes_are_retryable():
    for error in (
        LLMProviderHTTPError(429, "slow down"),
        LLMProviderHTTPError(529, "Overloaded"),
        httpx.ReadTimeout("read"),
        httpx.ConnectError("refused"),
    ):
        failure = classify_llm_failure(error)
        assert failure is not None
        assert failure.retryable


def test_the_detail_round_trips_as_plain_data():
    failure = classify_llm_failure(LLMProviderHTTPError(401, "invalid key"))

    assert failure is not None
    detail = failure.as_detail()
    assert detail[LLM_FAILURE_DETAIL]["cause"] == "provider_auth"
    assert detail[LLM_FAILURE_DETAIL]["message"] == failure.message
