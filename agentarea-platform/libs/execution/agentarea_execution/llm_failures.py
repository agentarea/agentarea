"""What a failed model call was, in words the workspace can act on.

The activity that calls the model holds the provider's exception; the workflow
only receives its text. The activity classifies the failure here and ships the
result in the failure's details, so every event about it carries the same cause.
"""

import json
import re
from dataclasses import asdict, dataclass
from typing import Any

LLM_FAILURE_DETAIL = "llm_failure"

_PROVIDER_MESSAGE_LIMIT = 300
_BILLING_UNAVAILABLE = "Billing is temporarily unavailable. Please try again later."
_OUT_OF_CREDITS_PHRASES = (
    "insufficient credits",
    "insufficient balance",
    "insufficient funds",
    "insufficient_quota",
    "exceeded your current quota",
    "out of credits",
    "requires more credits",
    "payment required",
    "no resource package",
    "please recharge",
)
_CONTEXT_WINDOW_PHRASES = (
    "context_length_exceeded",
    "maximum context length",
    "maximum context limit",
    "longer than the model's context length",
    "exceed context limit",
    "exceeds the available context size",
    "exceeds the maximum number of tokens allowed",
    "input tokens exceed the configured limit",
    "prompt is too long",
    "input is too long",
    "too many tokens",
)
_CONTENT_POLICY_PHRASES = (
    "content_policy_violation",
    "responsibleaipolicyviolation",
    "content management policy",
    "content_filter",
    "as a result of our safety system",
)
_REJECTED_REQUEST_STATUSES = (400, 413, 422)
_JSON_MESSAGE = re.compile(r'"message"\s*:\s*("(?:[^"\\]|\\.)*")')
_JSON_CODE_402 = re.compile(r'"code"\s*:\s*"?402\b')
_EXCEPTION_PREFIX = re.compile(r"^\w+(?:Error|Exception)?:\s*")


@dataclass(frozen=True)
class LLMFailure:
    """A classified model-call failure: a stable cause and what to tell the user."""

    cause: str
    message: str
    error_type: str
    retryable: bool

    def as_detail(self) -> dict[str, dict[str, Any]]:
        return {LLM_FAILURE_DETAIL: asdict(self)}


def _chain(error: BaseException) -> list[BaseException]:
    seen: list[BaseException] = []
    current: BaseException | None = error
    while current is not None and current not in seen:
        seen.append(current)
        current = current.__cause__ or current.__context__
    return seen


def _status_code(errors: list[BaseException]) -> int | None:
    for error in errors:
        status = getattr(error, "status_code", None)
        if isinstance(status, int) and not isinstance(status, bool):
            return status
        response = getattr(error, "response", None)
        status = getattr(response, "status_code", None)
        if isinstance(status, int) and not isinstance(status, bool):
            return status
    return None


def _provider_message(errors: list[BaseException]) -> str:
    """The provider's own sentence, without SDK prefixes or the JSON around it."""
    for error in errors:
        provider_message = getattr(error, "provider_message", None)
        if isinstance(provider_message, str) and provider_message.strip():
            return provider_message.strip()[:_PROVIDER_MESSAGE_LIMIT]
    text = str(errors[0])
    for error in errors:
        candidate = str(error)
        if _JSON_MESSAGE.search(candidate):
            text = candidate
            break
    match = _JSON_MESSAGE.search(text)
    if match:
        try:
            text = json.loads(match.group(1))
        except ValueError:
            text = match.group(1).strip('"')
    previous = None
    while previous != text:
        previous = text
        text = _EXCEPTION_PREFIX.sub("", text, count=1).strip()
    return text[:_PROVIDER_MESSAGE_LIMIT]


def _raised(errors: list[BaseException], *types: type[BaseException]) -> bool:
    return any(isinstance(error, types) for error in errors)


def _says(text: str, phrases: tuple[str, ...]) -> bool:
    return any(phrase in text for phrase in phrases)


def classify_llm_failure(error: BaseException) -> LLMFailure | None:
    """The cause of a failed model call, or None when it is not one we recognise."""
    # The workflow sandbox imports this module for LLM_FAILURE_DETAIL and refuses httpx;
    # only the activity classifies.
    import httpx

    errors = _chain(error)
    text = " ".join(f"{type(e).__name__} {e}" for e in errors).lower()
    status = _status_code(errors)

    if "failed to decrypt" in text:
        return LLMFailure(
            "credentials_undecryptable",
            "The provider's API key can no longer be decrypted (the encryption key changed). "
            "Re-enter the key in the provider settings.",
            "CredentialsUnreadable",
            retryable=False,
        )
    if "customer pricing failed" in text:
        return LLMFailure("pricing_unavailable", _BILLING_UNAVAILABLE, "BillingUnavailable", False)
    if "usage accounting unavailable" in text or "returned no usage" in text:
        return LLMFailure(
            "usage_unavailable",
            "The model provider did not report token usage for this call, so its cost "
            "cannot be accounted and the run was stopped. Try again or choose a different model.",
            "UsageUnavailable",
            retryable=False,
        )
    if "pricing is not configured" in text:
        return LLMFailure(
            "model_unpriced",
            "This model has no price configured, so the run's budget cannot be enforced. "
            "Set the model's pricing or choose a different model.",
            "ModelUnpriced",
            retryable=False,
        )
    if "effective policy is missing required runtime limit" in text:
        return LLMFailure(
            "policy_incomplete",
            "The run's policy sets no per-call token limit, so the model cannot be called. "
            "Check the workspace policy.",
            "ConfigurationError",
            retryable=False,
        )
    request_rejected = status is None or status in _REJECTED_REQUEST_STATUSES
    if request_rejected and _says(text, _CONTEXT_WINDOW_PHRASES):
        return LLMFailure(
            "context_window_exceeded",
            "The conversation no longer fits the model's context window. "
            "Start a new run or choose a model with a larger context window.",
            "ContextWindowExceeded",
            retryable=False,
        )
    if status == 402 or _JSON_CODE_402.search(text) or _says(text, _OUT_OF_CREDITS_PHRASES):
        return LLMFailure(
            "provider_out_of_credits",
            "The model provider's account is out of credits or quota, so it refused the call. "
            "Top up the provider account or choose a different model.",
            "ProviderQuotaExceeded",
            retryable=False,
        )
    if (
        status in (401, 403)
        or "invalid api key" in text
        or "incorrect api key" in text
        or "unauthorized" in text
    ):
        return LLMFailure(
            "provider_auth",
            "The model provider rejected the API key. Check the key in the provider settings.",
            "AuthenticationError",
            retryable=False,
        )
    if status == 429 or "rate limit" in text or "too many requests" in text:
        return LLMFailure(
            "rate_limited",
            "The model provider is rate-limiting requests. Please try again in a moment.",
            "RateLimitError",
            retryable=True,
        )
    if "quota exceeded" in text:
        return LLMFailure(
            "provider_out_of_credits",
            "The model provider's account is out of credits or quota, so it refused the call. "
            "Top up the provider account or choose a different model.",
            "ProviderQuotaExceeded",
            retryable=False,
        )
    if "deprecated" in text:
        return LLMFailure(
            "model_deprecated",
            "The configured model has been deprecated by the provider. "
            "Please select a different model.",
            "ModelDeprecated",
            retryable=False,
        )
    if status == 404:
        return LLMFailure(
            "model_not_found",
            "The configured model was not found. "
            "Please check the model name or select a different one.",
            "ModelNotFound",
            retryable=False,
        )
    if request_rejected and _says(text, _CONTENT_POLICY_PHRASES):
        return LLMFailure(
            "provider_content_policy",
            "The model provider refused the request under its content policy.",
            "ContentPolicyViolation",
            retryable=False,
        )
    if (
        status == 408
        or _raised(errors, httpx.TimeoutException, TimeoutError)
        or "timed out" in text
    ):
        return LLMFailure(
            "timeout",
            "The AI model request timed out. Please try again.",
            "TimeoutError",
            retryable=True,
        )
    if status is not None and 400 <= status < 500:
        return LLMFailure(
            "provider_bad_request",
            f"The model provider rejected the request: {_provider_message(errors)}",
            "ProviderBadRequest",
            retryable=False,
        )
    if (status is not None and status >= 500) or _raised(errors, httpx.TransportError):
        return LLMFailure(
            "provider_unavailable",
            "The model provider is unavailable right now. Please try again later.",
            "ProviderUnavailable",
            retryable=True,
        )
    return None
