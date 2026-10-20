"""LLM model for encapsulating litellm interactions."""

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any, cast

import httpx
import litellm
from litellm import (
    ModelResponse,
    acompletion,
)

from .messages import (
    AssistantMessage as SDKAssistantMessage,
)
from .messages import (
    SystemMessage as SDKSystemMessage,
)
from .messages import (
    ToolMessage as SDKToolMessage,
)
from .messages import (
    UserMessage as SDKUserMessage,
)

if TYPE_CHECKING:
    from agentarea_common.utils.url_safety import OutboundPolicy

logger = logging.getLogger(__name__)

# What a caller sees when the outbound policy refuses an endpoint. The guard's own
# message names the address the host resolved to, which would tell a member which
# internal names exist; that detail goes to the log only.
ENDPOINT_REFUSED = "the endpoint URL points to an address this deployment does not call"

# Configure LiteLLM callbacks via env to avoid noisy defaults during tests
import os as _os  # noqa: E402

_callbacks_env = _os.getenv("LITELLM_CALLBACKS")
if _callbacks_env is not None:
    try:
        litellm.callbacks = [cb.strip() for cb in _callbacks_env.split(",") if cb.strip()]
    except Exception:
        litellm.callbacks = []
else:
    # Default to no callbacks unless explicitly configured
    litellm.callbacks = []


class LLMProviderHTTPError(RuntimeError):
    """The provider answered a model call with an HTTP error status."""

    def __init__(self, status_code: int, provider_message: str) -> None:
        super().__init__(f"Provider returned HTTP {status_code}: {provider_message}")
        self.status_code = status_code
        self.provider_message = provider_message


def _error_body_message(body: bytes) -> str:
    """The provider's own words from an error response body."""
    text = body.decode("utf-8", errors="replace").strip()
    try:
        parsed = json.loads(text)
    except ValueError:
        return text[:500]
    error = parsed.get("error") if isinstance(parsed, dict) else None
    if isinstance(error, dict) and isinstance(error.get("message"), str):
        return error["message"][:500]
    if isinstance(error, str):
        return error[:500]
    if isinstance(parsed, dict) and isinstance(parsed.get("message"), str):
        return parsed["message"][:500]
    return text[:500]


@dataclass
class LLMRequest:
    """Request parameters for LLM calls."""

    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]] | None = None
    temperature: float | None = None
    max_tokens: int | None = None


@dataclass
class LLMUsage:
    """Token usage information from LLM response.

    ``prompt_tokens`` counts every prompt token, cached or not; the cache
    counts say how many of them were read from (or written to) the provider's
    prompt cache.
    """

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cached_prompt_tokens: int = 0
    cache_creation_tokens: int = 0


def _fields(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if hasattr(raw, "model_dump"):
        return raw.model_dump()
    return dict(getattr(raw, "__dict__", {}))


def _tokens(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return 0
    return max(int(value), 0)


def provider_reported_cost(raw: Any) -> Decimal | None:
    """What the provider says the call cost, in USD (OpenRouter's ``usage.cost``).

    The actual charge, which the declared per-token prices only approximate: a
    provider may bill differently (peak hours, another host). None when not reported.
    """
    value = _fields(raw).get("cost")
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return None
    try:
        cost = Decimal(str(value))
    except ArithmeticError:
        return None
    return cost if cost.is_finite() and cost >= 0 else None


def usage_from_provider(raw: Any) -> LLMUsage:
    """Read a provider's usage block, in OpenAI, Anthropic or LiteLLM shape.

    A block without ``total_tokens`` totals its parts; one without any counts
    stays at zero, which callers treat as no usage reported.
    """
    fields = _fields(raw)
    details = _fields(fields.get("prompt_tokens_details"))
    cache_read = _tokens(fields.get("cache_read_input_tokens"))
    cache_write = _tokens(fields.get("cache_creation_input_tokens"))
    if fields.get("prompt_tokens") is None and fields.get("input_tokens") is not None:
        prompt = _tokens(fields.get("input_tokens")) + cache_read + cache_write
        completion = _tokens(fields.get("output_tokens"))
    else:
        prompt = _tokens(fields.get("prompt_tokens"))
        completion = _tokens(fields.get("completion_tokens"))
    cached = (
        _tokens(details.get("cached_tokens"))
        or cache_read
        or _tokens(fields.get("prompt_cache_hit_tokens"))
    )
    return LLMUsage(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=_tokens(fields.get("total_tokens")) or prompt + completion,
        cached_prompt_tokens=min(cached, prompt),
        cache_creation_tokens=_tokens(details.get("cache_creation_tokens")) or cache_write,
    )


@dataclass
class LLMResponse:
    """Standardized LLM response format."""

    content: str
    role: str
    tool_calls: list[dict[str, Any]] | None = None
    cost: Decimal = Decimal(0)
    usage: LLMUsage | None = None
    reasoning_content: str = ""


class LLMModel:
    """Encapsulates LLM model logic using litellm."""

    def __init__(
        self,
        provider_type: str,
        model_name: str,
        api_key: str | None = None,
        endpoint_url: str | None = None,
        input_cost_per_token: Decimal | None = None,
        output_cost_per_token: Decimal | None = None,
        cached_input_cost_per_token: Decimal | None = None,
        endpoint_policy: OutboundPolicy | None = None,
        cache_creation_input_cost_per_token: Decimal | None = None,
    ):
        """Initialize LLM model with explicit parameters.

        Args:
            provider_type: The LLM provider type (e.g., "openai", "anthropic", "ollama_chat")
            model_name: The model name (e.g., "gpt-3.5-turbo", "claude-3-opus")
            api_key: API key for the provider (optional for local models)
            endpoint_url: Custom endpoint URL (optional, uses provider defaults)
            input_cost_per_token: Persisted input-token price; zero means explicitly free.
            output_cost_per_token: Persisted output-token price; zero means explicitly free.
            cached_input_cost_per_token: Price of a prompt token read from the provider's
                cache; None prices cached tokens as any other input token.
            cache_creation_input_cost_per_token: Price of a prompt token written to the
                provider's cache; None prices it as any other input token.
            endpoint_policy: Set when ``endpoint_url`` came from someone other than
                whoever runs this process (a workspace member): every call to it is
                refused unless the address passes this policy. None calls it as given.
        """
        self.provider_type = provider_type
        self.model_name = model_name
        self.api_key = api_key
        self.endpoint_url = endpoint_url
        self.input_cost_per_token = input_cost_per_token
        self.output_cost_per_token = output_cost_per_token
        self.cached_input_cost_per_token = cached_input_cost_per_token
        self.cache_creation_input_cost_per_token = cache_creation_input_cost_per_token
        self.endpoint_policy = endpoint_policy

    def _configured_cost(self, usage: LLMUsage) -> Decimal:
        """Calculate cost from the persisted model spec.

        ``None`` means pricing is unknown. Zero is accepted as an explicit free
        model price; callers decide whether unknown pricing is admissible.
        """
        if self.input_cost_per_token is None or self.output_cost_per_token is None:
            return Decimal(0)
        input_rate = Decimal(str(self.input_cost_per_token))
        cached = (
            min(usage.cached_prompt_tokens, usage.prompt_tokens)
            if self.cached_input_cost_per_token is not None
            else 0
        )
        cached_rate = Decimal(str(self.cached_input_cost_per_token)) if cached else Decimal(0)
        written = (
            min(usage.cache_creation_tokens, usage.prompt_tokens - cached)
            if self.cache_creation_input_cost_per_token is not None
            else 0
        )
        written_rate = (
            Decimal(str(self.cache_creation_input_cost_per_token)) if written else Decimal(0)
        )
        return (
            (usage.prompt_tokens - cached - written) * input_rate
            + cached * cached_rate
            + written * written_rate
            + usage.completion_tokens * Decimal(str(self.output_cost_per_token))
        )

    def _safe_json_serialize(self, obj: Any) -> str:
        """Convert any Python object to JSON-serializable string safely."""
        try:
            return json.dumps(obj, ensure_ascii=False)
        except TypeError, OverflowError:
            return str(obj)

    def _to_content_parts(self, content: Any, metadata: dict[str, Any] | None = None) -> Any:
        """Return content in a form accepted by LiteLLM/OpenAI:
        - If metadata contains 'content_parts' list, use it directly (for multimodal)
        - If content is already list/dict (OpenAI format), pass through
        - If content is a JSON string representing list/dict, parse
        - Else return string content as-is
        """
        # Priority: explicit content_parts in metadata
        if metadata and isinstance(metadata, dict):
            parts = metadata.get("content_parts")
            if parts is not None:
                return parts

        # Pass through structured content
        if isinstance(content, list | dict):
            return content

        # Try to parse JSON-encoded content into structured parts
        if isinstance(content, str):
            c = content.strip()
            if (c.startswith("{") and c.endswith("}")) or (c.startswith("[") and c.endswith("]")):
                try:
                    parsed = json.loads(c)
                    if isinstance(parsed, list | dict):
                        return parsed
                except Exception:
                    logger.debug("Message content is not JSON; passing it as text", exc_info=True)
            return content

        # Fallback to string
        return str(content)

    def _normalize_message(self, msg: Any) -> Any:
        """Normalize an SDK message or dict to LiteLLM-typed message or OpenAI dict.
        - System messages mapped to ChatCompletionSystemMessage
        - User/Assistant/Tool messages converted to typed classes when appropriate
        - Assistant tool_calls mapped to ChatCompletionAssistantToolCall + Function
        - Supports multimodal by accepting list/dict content or metadata.content_parts
        """
        # SDK dataclass messages
        if isinstance(msg, SDKSystemMessage):
            return {
                "role": "system",
                "content": self._to_content_parts(msg.content, msg.metadata),
            }
        if isinstance(msg, SDKUserMessage):
            return {
                "role": "user",
                "content": self._to_content_parts(msg.content, msg.metadata),
            }
        if isinstance(msg, SDKToolMessage):
            return {
                "role": "tool",
                "tool_call_id": msg.tool_call_id,
                "content": self._safe_json_serialize(msg.content),
            }
        if isinstance(msg, SDKAssistantMessage):
            tool_calls = None
            if msg.tool_calls:
                tool_calls = []
                for tc in msg.tool_calls:
                    try:
                        fn = {}
                        if isinstance(tc, dict) and "function" in tc:
                            fn_src = tc["function"]
                            fn = {
                                "name": fn_src.get("name", ""),
                                "arguments": fn_src.get("arguments", ""),
                            }
                        tool_calls.append(
                            {
                                "id": tc.get("id", ""),
                                "type": tc.get("type", "function"),
                                "function": fn,
                            }
                        )
                    except Exception:
                        logger.warning("Dropping malformed tool call from message", exc_info=True)
            return {
                "role": "assistant",
                "content": self._to_content_parts(msg.content, msg.metadata),
                **({"tool_calls": tool_calls} if tool_calls else {}),
            }

        # If it's already a dict/list in OpenAI format, return as-is
        if isinstance(msg, dict | list):
            return msg

        # Any object exposing role/content
        if hasattr(msg, "role") and hasattr(msg, "content"):
            return {"role": msg.role, "content": msg.content}

        # Otherwise return message unchanged
        return msg

    def _normalize_messages(self, messages: list[Any]) -> list[Any]:
        return [self._normalize_message(m) for m in messages]

    def _build_litellm_params(self, request: LLMRequest) -> dict[str, Any]:
        """Build parameters for litellm API call."""
        # Prefer provider-prefixed model if provider_type is available (e.g., "ollama_chat/qwen2.5")
        litellm_model = (
            f"{self.provider_type}/{self.model_name}" if self.provider_type else self.model_name
        )
        params: dict[str, Any] = {
            "model": litellm_model,
        }

        # Messages normalization: support SDK typed messages and dicts
        if request.messages:
            normalized_messages = self._normalize_messages(request.messages)
            params["messages"] = normalized_messages
        else:
            params["messages"] = []

        # Add API key if available
        if self.api_key:
            params["api_key"] = self.api_key

        # Handle base URL for custom endpoints
        if self.endpoint_url:
            url = self.endpoint_url
            if not url.startswith("http"):
                url = f"http://{url}"
            params["base_url"] = url

        # Add tools if provided
        if request.tools:
            params["tools"] = request.tools
            params["tool_choice"] = "auto"

        # Add optional parameters
        if request.temperature is not None:
            params["temperature"] = request.temperature
        if request.max_tokens is not None:
            params["max_tokens"] = request.max_tokens

        return params

    def _get_base_url(self) -> str | None:
        """Resolve the base URL for direct HTTP calls."""
        if self.endpoint_url:
            url = self.endpoint_url
            if not url.startswith("http"):
                url = f"http://{url}"
            return url.rstrip("/")
        return None

    def _pins_endpoint(self) -> bool:
        """Whether calls must go through the pinned client rather than LiteLLM.

        LiteLLM connects with its own client and follows redirects, so a public
        address answering 307 to an internal one would pass any check made before
        the call. The pinned client vets every hop it connects to.
        """
        return self.endpoint_policy is not None and self._get_base_url() is not None

    async def _check_endpoint(self) -> None:
        """A pre-check for the LiteLLM path that has no pinned equivalent.

        Resolves the name once and LiteLLM resolves it again and may follow a
        redirect; every path the platform calls goes through the pinned client.
        """
        base_url = self._get_base_url()
        if self.endpoint_policy is None or base_url is None:
            return
        from agentarea_common.utils.url_safety import UnsafeUrlError, validate_outbound_url

        try:
            await asyncio.to_thread(validate_outbound_url, base_url, policy=self.endpoint_policy)
        except UnsafeUrlError as e:
            logger.warning(f"Endpoint refused by the outbound policy: {e}")
            raise UnsafeUrlError(ENDPOINT_REFUSED) from None

    async def _send(self, client: httpx.AsyncClient, request: httpx.Request) -> httpx.Response:
        from agentarea_common.utils.url_safety import UnsafeUrlError

        try:
            return await client.send(request, stream=True)
        except UnsafeUrlError as e:
            logger.warning(f"Endpoint refused by the outbound policy: {e}")
            raise UnsafeUrlError(ENDPOINT_REFUSED) from None

    def _http_client(self, timeout: httpx.Timeout) -> httpx.AsyncClient:
        from agentarea_common.utils.outbound_tls import outbound_ssl_context

        if self.endpoint_policy is None:
            return httpx.AsyncClient(timeout=timeout, verify=outbound_ssl_context())
        from agentarea_common.utils.url_safety import safe_async_client

        return safe_async_client(policy=self.endpoint_policy, timeout=timeout)

    def _supports_direct_streaming(self) -> bool:
        """Whether we can stream from the endpoint ourselves instead of via LiteLLM.

        The only requirement is an explicit endpoint: a provider that gave us
        a base URL is one we can speak OpenAI-compatible HTTP to directly,
        which is how reasoning/thinking deltas survive — LiteLLM drops them
        while streaming.

        The provider's *name* says nothing about this. There used to be a
        branch matching one vendor by substring, but ``_get_base_url()``
        returns a URL only when ``endpoint_url`` is set, so reaching that
        branch already implied the answer was yes; it could never change the
        result.
        """
        return self._get_base_url() is not None

    async def _stream_openai_compatible(self, request: LLMRequest) -> AsyncIterator[LLMResponse]:
        """Stream from an OpenAI-compatible API directly via httpx.

        This bypasses LiteLLM's streaming to properly capture reasoning/thinking
        content that LiteLLM drops. Works with any provider that exposes an
        OpenAI-compatible /v1/chat/completions endpoint (Ollama, vLLM, etc.).
        """
        base_url = self._get_base_url()
        if not base_url:
            raise ValueError("No base URL configured for direct HTTP completion call")
        # OpenAI-SDK convention is that the base URL ends in /v1 (e.g.
        # https://api.openai.com/v1, http://localhost:1234/v1). Tolerate both
        # forms — endpoint_url with or without a trailing /v1 — so users can
        # paste either the proxy root or the standard /v1 base URL.
        suffix = (
            "/chat/completions" if base_url.rstrip("/").endswith("/v1") else "/v1/chat/completions"
        )
        url = f"{base_url.rstrip('/')}{suffix}"

        normalized_messages = self._normalize_messages(request.messages)

        payload: dict[str, Any] = {
            "model": self.model_name,
            "messages": normalized_messages,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if request.tools:
            payload["tools"] = request.tools
            payload["tool_choice"] = "auto"
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        tool_calls_buffer: dict[int, dict[str, Any]] = {}
        final_usage: LLMUsage | None = None
        final_cost = Decimal(0)

        async with self._http_client(httpx.Timeout(300.0)) as client:
            # Try with thinking enabled first; fall back without if provider rejects it
            use_payload = {**payload, "think": True}
            resp = await self._send(
                client, client.build_request("POST", url, json=use_payload, headers=headers)
            )
            if resp.status_code >= 400:
                await resp.aclose()
                logger.info("Provider rejected 'think' param, retrying without it")
                resp = await self._send(
                    client, client.build_request("POST", url, json=payload, headers=headers)
                )
                if resp.status_code >= 400:
                    body = await resp.aread()
                    await resp.aclose()
                    raise LLMProviderHTTPError(resp.status_code, _error_body_message(body))

            try:
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data_str = line[5:].strip()
                    if data_str == "[DONE]":
                        break

                    try:
                        chunk = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    usage_data = chunk.get("usage")
                    if usage_data:
                        final_usage = usage_from_provider(usage_data)
                        reported = provider_reported_cost(usage_data)
                        final_cost = (
                            reported if reported is not None else self._configured_cost(final_usage)
                        )

                    choices = chunk.get("choices", [])
                    if not choices:
                        if final_usage is not None:
                            yield LLMResponse(
                                content="",
                                role="assistant",
                                cost=final_cost,
                                usage=final_usage,
                            )
                        continue

                    delta = choices[0].get("delta", {})

                    # Extract content
                    delta_content = delta.get("content") or ""

                    # Extract reasoning — different providers use different field names
                    delta_reasoning = (
                        delta.get("reasoning_content")
                        or delta.get("reasoning")
                        or delta.get("thinking")
                        or ""
                    )

                    # Extract tool calls
                    delta_tool_calls = None
                    if delta.get("tool_calls"):
                        for tc_delta in delta["tool_calls"]:
                            idx = tc_delta.get("index", 0)
                            if idx not in tool_calls_buffer:
                                tool_calls_buffer[idx] = {
                                    "id": "",
                                    "type": "function",
                                    "function": {"name": "", "arguments": ""},
                                }
                            if tc_delta.get("id"):
                                tool_calls_buffer[idx]["id"] = tc_delta["id"]
                            fn = tc_delta.get("function", {})
                            if fn.get("name"):
                                tool_calls_buffer[idx]["function"]["name"] = fn["name"]
                            if fn.get("arguments"):
                                tool_calls_buffer[idx]["function"]["arguments"] += fn["arguments"]

                        delta_tool_calls = [
                            tool_calls_buffer[i] for i in sorted(tool_calls_buffer.keys())
                        ]

                    usage_delta = final_usage if usage_data else None

                    if delta_content or delta_reasoning or delta_tool_calls or usage_delta:
                        yield LLMResponse(
                            content=delta_content,
                            role="assistant",
                            tool_calls=delta_tool_calls,
                            reasoning_content=delta_reasoning,
                            cost=final_cost if usage_delta is not None else Decimal(0),
                            usage=usage_delta,
                        )
            finally:
                await resp.aclose()

    def _parse_response(self, response: ModelResponse) -> LLMResponse:
        """Parse litellm response into standardized format."""
        message = response.choices[0].message

        # Handle tool calls
        tool_calls = None
        if hasattr(message, "tool_calls") and message.tool_calls:
            # Narrowed on `type`: openai's union gained
            # ChatCompletionMessageCustomToolCall, which carries no `function`.
            # We never advertise custom tools, so one arriving means the provider
            # invented it — say so rather than dropping it from the transcript,
            # where it would look like the model simply never called anything.
            for tool_call in message.tool_calls:
                if tool_call.type != "function":
                    logger.warning(
                        "Ignoring unsupported tool call type %r from the model", tool_call.type
                    )
            tool_calls = [
                {
                    "id": tool_call.id,
                    "type": tool_call.type,
                    "function": {
                        "name": tool_call.function.name,
                        "arguments": tool_call.function.arguments,
                    },
                }
                for tool_call in message.tool_calls
                if tool_call.type == "function"
            ]
        elif hasattr(message, "function_call") and message.function_call:
            # Fallback for providers that use function_call instead of tool_calls
            fc = message.function_call
            tool_calls = [
                {
                    "id": "",
                    "type": "function",
                    "function": {
                        "name": getattr(fc, "name", ""),
                        "arguments": getattr(fc, "arguments", "") or "",
                    },
                }
            ]

        # Calculate cost information
        cost = Decimal(0)
        usage = LLMUsage()

        response_usage = getattr(response, "usage", None)
        if response_usage:
            # Update usage statistics
            usage = usage_from_provider(response_usage)

            reported = provider_reported_cost(response_usage)
            if reported is not None:
                cost = reported
            else:
                # litellm includes cost calculation in some cases
                if hasattr(response_usage, "completion_tokens_cost"):
                    cost += Decimal(str(getattr(response_usage, "completion_tokens_cost", 0.0)))
                if hasattr(response_usage, "prompt_tokens_cost"):
                    cost += Decimal(str(getattr(response_usage, "prompt_tokens_cost", 0.0)))
                if cost == 0.0:
                    cost = self._configured_cost(usage)

        # Follow OpenAI standard: when tool_calls are present, content should be minimal
        content = message.content or ""

        return LLMResponse(
            content=content,
            role=message.role,
            tool_calls=tool_calls,
            cost=cost,
            usage=usage,
            reasoning_content=(
                getattr(message, "reasoning_content", None)
                or getattr(message, "reasoning", None)
                or getattr(message, "thinking", None)
                or ""
            ),
        )

    async def _complete_through_pinned_client(
        self, request: LLMRequest, event_publisher: Any = None
    ) -> LLMResponse:
        content: list[str] = []
        reasoning: list[str] = []
        tool_calls: list[dict[str, Any]] | None = None
        usage: LLMUsage | None = None
        cost = Decimal(0)
        async for chunk in self._stream_openai_compatible(request):
            if event_publisher and chunk.content:
                await event_publisher(chunk.content, len(content), False)
            content.append(chunk.content)
            reasoning.append(chunk.reasoning_content)
            if chunk.tool_calls:
                tool_calls = chunk.tool_calls
            if chunk.usage is not None:
                usage = chunk.usage
                cost = chunk.cost
        if event_publisher:
            await event_publisher("", len(content), True)
        return LLMResponse(
            content="".join(content),
            role="assistant",
            tool_calls=tool_calls,
            cost=cost,
            usage=usage,
            reasoning_content="".join(reasoning),
        )

    async def complete(self, request: LLMRequest) -> LLMResponse:
        """Call LLM with the provided request."""
        try:
            if self._pins_endpoint():
                return await self._complete_through_pinned_client(request)

            # Build parameters
            params = self._build_litellm_params(request)

            logger.info(f"Calling LLM with model {params['model']}")

            # Make the LLM call
            typed_response = cast(ModelResponse, await acompletion(**params))

            # Parse and return response
            result = self._parse_response(typed_response)
            logger.info(f"LLM call completed successfully, cost: ${result.cost:.6f}")
            return result

        except Exception as e:
            # Enhanced error logging with context
            error_context = {
                "provider_type": self.provider_type,
                "model_name": self.model_name,
                "has_api_key": bool(self.api_key),
                "endpoint_url": self.endpoint_url,
                "error_type": type(e).__name__,
                "error_message": str(e),
            }

            logger.exception(f"LLM call failed with context: {error_context}")

            # Re-raise with original exception to preserve stack trace
            raise

    async def complete_with_streaming(
        self, request: LLMRequest, task_id: str, agent_id: str, execution_id: str, event_publisher
    ) -> LLMResponse:
        """Call LLM with streaming and emit chunk events."""
        try:
            if self._pins_endpoint():
                return await self._complete_through_pinned_client(request, event_publisher)

            # Build parameters for streaming
            params = self._build_litellm_params(request)
            params["stream"] = True
            params["stream_options"] = {"include_usage": True}

            logger.info(f"Calling LLM with streaming for model {params['model']}")
            await self._check_endpoint()

            # Make the streaming LLM call
            # LiteLLM's stream overload does not describe its chunk shape.
            response_stream = cast(AsyncIterator[Any], await acompletion(**params))

            # Collect streaming response
            complete_content = ""
            chunk_index = 0
            usage_info = None
            cost = Decimal(0)
            tool_calls = []
            tool_calls_buffer = {}  # Buffer for streaming tool calls

            async for chunk in response_stream:
                # chunk: ModelResponse
                if chunk.choices:
                    delta = chunk.choices[0].delta

                    # Handle content chunks
                    if hasattr(delta, "content") and delta.content:
                        complete_content += delta.content

                        # Emit chunk event
                        if event_publisher:
                            await event_publisher(delta.content, chunk_index, False)
                        chunk_index += 1

                    # Handle tool calls in streaming - proper implementation
                    if hasattr(delta, "tool_calls") and delta.tool_calls:
                        for tool_call_delta in delta.tool_calls:
                            index = getattr(tool_call_delta, "index", 0)

                            # Initialize tool call buffer for this index if needed
                            if index not in tool_calls_buffer:
                                tool_calls_buffer[index] = {
                                    "id": "",
                                    "type": "function",
                                    "function": {"name": "", "arguments": ""},
                                }

                            # Update tool call buffer with delta information
                            if hasattr(tool_call_delta, "id") and tool_call_delta.id:
                                tool_calls_buffer[index]["id"] = tool_call_delta.id

                            if hasattr(tool_call_delta, "type") and tool_call_delta.type:
                                tool_calls_buffer[index]["type"] = tool_call_delta.type

                            if hasattr(tool_call_delta, "function") and tool_call_delta.function:
                                function_delta = tool_call_delta.function

                                if hasattr(function_delta, "name") and function_delta.name:
                                    tool_calls_buffer[index]["function"]["name"] = (
                                        function_delta.name
                                    )

                                if (
                                    hasattr(function_delta, "arguments")
                                    and function_delta.arguments
                                ):
                                    # Handle JSON arguments properly to avoid concatenation issues
                                    current_args = tool_calls_buffer[index]["function"]["arguments"]
                                    new_args = function_delta.arguments

                                    # If current_args is empty, just use new_args
                                    if not current_args:
                                        tool_calls_buffer[index]["function"]["arguments"] = new_args
                                    else:
                                        # Try to parse and merge JSON properly
                                        try:
                                            # Check if current_args is valid JSON
                                            current_json = json.loads(current_args)
                                            # If new_args is also valid JSON, merge them
                                            try:
                                                new_json = json.loads(new_args)
                                                # Merge the JSON objects
                                                current_json.update(new_json)
                                                tool_calls_buffer[index]["function"][
                                                    "arguments"
                                                ] = json.dumps(current_json)
                                            except json.JSONDecodeError:
                                                # If new_args is not valid JSON, append as string
                                                tool_calls_buffer[index]["function"][
                                                    "arguments"
                                                ] = current_args + new_args
                                        except json.JSONDecodeError:
                                            # If current_args is not valid JSON, just concatenate
                                            tool_calls_buffer[index]["function"]["arguments"] = (
                                                current_args + new_args
                                            )

                    # Fallback: some providers stream legacy function_call instead of tool_calls
                    if hasattr(delta, "function_call") and delta.function_call:
                        fc = delta.function_call
                        index = 0
                        if index not in tool_calls_buffer:
                            tool_calls_buffer[index] = {
                                "id": "",
                                "type": "function",
                                "function": {"name": "", "arguments": ""},
                            }
                        if hasattr(fc, "name") and fc.name:
                            tool_calls_buffer[index]["function"]["name"] = fc.name
                        if hasattr(fc, "arguments") and fc.arguments:
                            current_args = tool_calls_buffer[index]["function"]["arguments"]
                            new_args = fc.arguments
                            if not current_args:
                                tool_calls_buffer[index]["function"]["arguments"] = new_args
                            else:
                                try:
                                    current_json = json.loads(current_args)
                                    try:
                                        new_json = json.loads(new_args)
                                        current_json.update(new_json)
                                        tool_calls_buffer[index]["function"]["arguments"] = (
                                            json.dumps(current_json)
                                        )
                                    except json.JSONDecodeError:
                                        tool_calls_buffer[index]["function"]["arguments"] = (
                                            current_args + new_args
                                        )
                                except json.JSONDecodeError:
                                    tool_calls_buffer[index]["function"]["arguments"] = (
                                        current_args + new_args
                                    )
                # Extract cost from _hidden_params (LiteLLM sets this per chunk)
                if hasattr(chunk, "_hidden_params"):
                    hidden = chunk._hidden_params
                    rc = (
                        hidden.get("response_cost", 0.0)
                        if isinstance(hidden, dict)
                        else getattr(hidden, "response_cost", 0.0)
                    ) or 0.0
                    if rc > 0.0:
                        cost = Decimal(str(rc))

                # Extract usage from final chunk if available
                if hasattr(chunk, "usage") and chunk.usage:
                    usage_info = chunk.usage
                    reported = provider_reported_cost(usage_info)
                    if reported is not None:
                        cost = reported
                    elif cost == 0.0:
                        if hasattr(usage_info, "completion_tokens_cost"):
                            cost += Decimal(str(getattr(usage_info, "completion_tokens_cost", 0.0)))
                            if hasattr(usage_info, "prompt_tokens_cost"):
                                cost += Decimal(str(getattr(usage_info, "prompt_tokens_cost", 0.0)))

            # Convert tool calls buffer to final format
            if tool_calls_buffer:
                tool_calls = [tool_calls_buffer[i] for i in sorted(tool_calls_buffer.keys())]

            # Emit final chunk event
            if event_publisher:
                await event_publisher("", chunk_index, True)

            # Create usage object
            usage = LLMUsage()
            if usage_info:
                usage = usage_from_provider(usage_info)
                if cost == 0.0:
                    cost = self._configured_cost(usage)

            # Use litellm.completion_cost() for accurate cost calculation
            if cost == 0.0 and (
                self.input_cost_per_token is None or self.output_cost_per_token is None
            ):
                try:
                    import litellm

                    model_str = (
                        f"{self.provider_type}/{self.model_name}"
                        if self.provider_type
                        else self.model_name
                    )
                    prompt_tokens = getattr(usage_info, "prompt_tokens", 0) if usage_info else 0
                    completion_tokens = (
                        getattr(usage_info, "completion_tokens", 0) if usage_info else 0
                    )

                    # If usage wasn't in chunks, estimate tokens from content
                    if prompt_tokens == 0:
                        prompt_tokens = litellm.token_counter(
                            model=model_str,
                            messages=request.messages,
                        )
                    if completion_tokens == 0 and complete_content:
                        completion_tokens = litellm.token_counter(
                            model=model_str, text=complete_content
                        )

                    if prompt_tokens > 0 or completion_tokens > 0:
                        prompt_str = " ".join(
                            m.get("content", "") if isinstance(m, dict) else str(m)
                            for m in request.messages
                        )
                        cost = Decimal(
                            str(
                                litellm.completion_cost(
                                    model=model_str,
                                    prompt=prompt_str,
                                    completion=complete_content or "",
                                )
                            )
                        )
                        # Update usage if it was estimated
                        if usage_info is None:
                            usage = LLMUsage(
                                prompt_tokens=prompt_tokens,
                                completion_tokens=completion_tokens,
                                total_tokens=prompt_tokens + completion_tokens,
                            )
                except Exception as e:
                    logger.warning(f"Failed to calculate cost via litellm: {e}", exc_info=True)

            # Return complete response
            result = LLMResponse(
                content=complete_content,
                role="assistant",
                tool_calls=tool_calls,
                cost=cost,
                usage=usage,
            )

            logger.info(
                f"Streaming LLM call completed successfully, "
                f"cost: ${result.cost:.6f}, chunks: {chunk_index}"
            )
            return result

        except Exception as e:
            # Enhanced error logging with context
            error_context = {
                "provider_type": self.provider_type,
                "model_name": self.model_name,
                "has_api_key": bool(self.api_key),
                "endpoint_url": self.endpoint_url,
                "error_type": type(e).__name__,
                "error_message": str(e),
                "streaming": True,
            }

            logger.exception(f"Streaming LLM call failed with context: {error_context}")

            # Re-raise with original exception to preserve stack trace
            raise

    async def ainvoke_stream(self, request: LLMRequest) -> AsyncIterator[LLMResponse]:
        """Call LLM with streaming and yield responses as they arrive.

        Uses direct OpenAI-compatible HTTP streaming when available (to properly
        capture reasoning/thinking content). Falls back to LiteLLM for providers
        without a known base URL.

        Args:
            request: The LLM request parameters

        Yields:
            LLMResponse objects containing delta responses (only new content)
        """
        # Use direct streaming for OpenAI-compatible providers to capture thinking
        if self._supports_direct_streaming():
            logger.info(
                f"Using direct OpenAI-compatible streaming for provider {self.provider_type}"
            )
            async for response in self._stream_openai_compatible(request):
                yield response
            return

        try:
            # Build parameters for streaming
            params = self._build_litellm_params(request)
            params["stream"] = True
            # OpenAI-compatible providers emit token usage in a trailing,
            # choices-less chunk only when explicitly requested. Without it,
            # governed workflows must fail closed because neither token nor
            # cost limits can be enforced.
            params["stream_options"] = {"include_usage": True}

            logger.info(f"Starting streaming LLM call for model {params['model']}")

            # Make the streaming LLM call
            # LiteLLM's stream overload does not describe its chunk shape.
            response_stream = cast(AsyncIterator[Any], await litellm.acompletion(**params))

            # Process streaming response
            complete_content = ""  # Keep track for tool calls and final usage
            complete_reasoning = ""  # Track reasoning/thinking content
            tool_calls_buffer = {}  # Buffer for streaming tool calls
            usage = LLMUsage()
            cost = Decimal(0)

            async for chunk in response_stream:
                # chunk: ModelResponse
                delta_content = ""
                delta_reasoning = ""
                delta_tool_calls = None
                tool_calls_updated = False

                if chunk.choices:
                    delta = chunk.choices[0].delta

                    # Handle reasoning/thinking chunks (LiteLLM exposes as reasoning_content)
                    if hasattr(delta, "reasoning_content") and delta.reasoning_content:
                        delta_reasoning = delta.reasoning_content
                        complete_reasoning += delta_reasoning

                    # Handle content chunks
                    if hasattr(delta, "content") and delta.content:
                        delta_content = delta.content
                        complete_content += delta_content

                    # Handle tool calls in streaming
                    if hasattr(delta, "tool_calls") and delta.tool_calls:
                        for tool_call_delta in delta.tool_calls:
                            index = getattr(tool_call_delta, "index", 0)

                            # Initialize tool call buffer for this index if needed
                            if index not in tool_calls_buffer:
                                tool_calls_buffer[index] = {
                                    "id": "",
                                    "type": "function",
                                    "function": {"name": "", "arguments": ""},
                                }

                            # Update tool call buffer with delta information
                            if hasattr(tool_call_delta, "id") and tool_call_delta.id:
                                tool_calls_buffer[index]["id"] = tool_call_delta.id
                                tool_calls_updated = True

                            if hasattr(tool_call_delta, "type") and tool_call_delta.type:
                                tool_calls_buffer[index]["type"] = tool_call_delta.type
                                tool_calls_updated = True

                            if hasattr(tool_call_delta, "function") and tool_call_delta.function:
                                function_delta = tool_call_delta.function

                                if hasattr(function_delta, "name") and function_delta.name:
                                    tool_calls_buffer[index]["function"]["name"] = (
                                        function_delta.name
                                    )
                                    tool_calls_updated = True

                                if (
                                    hasattr(function_delta, "arguments")
                                    and function_delta.arguments
                                ):
                                    # Handle JSON arguments properly to avoid concatenation issues
                                    current_args = tool_calls_buffer[index]["function"]["arguments"]
                                    new_args = function_delta.arguments

                                    # If current_args is empty, just use new_args
                                    if not current_args:
                                        tool_calls_buffer[index]["function"]["arguments"] = new_args
                                    else:
                                        # Try to parse and merge JSON properly
                                        try:
                                            # Check if current_args is valid JSON
                                            current_json = json.loads(current_args)
                                            # If new_args is also valid JSON, merge them
                                            try:
                                                new_json = json.loads(new_args)
                                                # Merge the JSON objects
                                                current_json.update(new_json)
                                                tool_calls_buffer[index]["function"][
                                                    "arguments"
                                                ] = json.dumps(current_json)
                                            except json.JSONDecodeError:
                                                # If new_args is not valid JSON, append as string
                                                tool_calls_buffer[index]["function"][
                                                    "arguments"
                                                ] = current_args + new_args
                                        except json.JSONDecodeError:
                                            # If current_args is not valid JSON, just concatenate
                                            tool_calls_buffer[index]["function"]["arguments"] = (
                                                current_args + new_args
                                            )
                                    tool_calls_updated = True

                    # Fallback: some providers stream legacy function_call instead of tool_calls
                    if hasattr(delta, "function_call") and delta.function_call:
                        fc = delta.function_call
                        index = 0
                        if index not in tool_calls_buffer:
                            tool_calls_buffer[index] = {
                                "id": "",
                                "type": "function",
                                "function": {"name": "", "arguments": ""},
                            }
                        if hasattr(fc, "name") and fc.name:
                            tool_calls_buffer[index]["function"]["name"] = fc.name
                            tool_calls_updated = True
                        if hasattr(fc, "arguments") and fc.arguments:
                            current_args = tool_calls_buffer[index]["function"]["arguments"]
                            new_args = fc.arguments
                            if not current_args:
                                tool_calls_buffer[index]["function"]["arguments"] = new_args
                            else:
                                try:
                                    current_json = json.loads(current_args)
                                    try:
                                        new_json = json.loads(new_args)
                                        current_json.update(new_json)
                                        tool_calls_buffer[index]["function"]["arguments"] = (
                                            json.dumps(current_json)
                                        )
                                    except json.JSONDecodeError:
                                        tool_calls_buffer[index]["function"]["arguments"] = (
                                            current_args + new_args
                                        )
                                except json.JSONDecodeError:
                                    tool_calls_buffer[index]["function"]["arguments"] = (
                                        current_args + new_args
                                    )
                            tool_calls_updated = True

                # Extract cost from _hidden_params (LiteLLM sets this per chunk)
                if hasattr(chunk, "_hidden_params"):
                    hidden = chunk._hidden_params
                    rc = (
                        hidden.get("response_cost", 0.0)
                        if isinstance(hidden, dict)
                        else getattr(hidden, "response_cost", 0.0)
                    ) or 0.0
                    if rc > 0.0:
                        cost = Decimal(str(rc))

                # Extract usage from final chunk if available
                if hasattr(chunk, "usage") and chunk.usage:
                    usage_info = chunk.usage
                    reported = provider_reported_cost(usage_info)
                    if reported is not None:
                        cost = reported
                    elif cost == 0.0:
                        if hasattr(usage_info, "completion_tokens_cost"):
                            cost += Decimal(str(getattr(usage_info, "completion_tokens_cost", 0.0)))
                            if hasattr(usage_info, "prompt_tokens_cost"):
                                cost += Decimal(str(getattr(usage_info, "prompt_tokens_cost", 0.0)))

                # Provide current tool call state if updated this chunk
                if tool_calls_updated:
                    delta_tool_calls = [
                        tool_calls_buffer[i] for i in sorted(tool_calls_buffer.keys())
                    ]

                # Yield delta response for each content, reasoning, or tool-calls update
                if (
                    delta_content
                    or delta_reasoning
                    or delta_tool_calls is not None
                    or (hasattr(chunk, "usage") and chunk.usage)
                ):
                    # Build usage object only when present on this chunk
                    usage_delta = None
                    if hasattr(chunk, "usage") and chunk.usage:
                        usage_delta = usage_from_provider(chunk.usage)
                        usage = usage_delta
                        if cost == 0.0:
                            cost = self._configured_cost(usage_delta)
                    yield LLMResponse(
                        content=delta_content,
                        role="assistant",
                        tool_calls=delta_tool_calls,
                        cost=cost,
                        usage=usage_delta,
                        reasoning_content=delta_reasoning,
                    )

            # Calculate cost after streaming ends using litellm.completion_cost()
            # _hidden_params.response_cost is NOT available on streaming chunks
            if cost == 0.0 and (
                self.input_cost_per_token is None or self.output_cost_per_token is None
            ):
                try:
                    model_str = (
                        f"{self.provider_type}/{self.model_name}"
                        if self.provider_type
                        else self.model_name
                    )
                    prompt_str = "\n".join(
                        m.get("content", "") if isinstance(m, dict) else str(m)
                        for m in request.messages
                    )
                    cost = Decimal(
                        str(
                            litellm.completion_cost(
                                model=model_str,
                                prompt=prompt_str,
                                completion=complete_content,
                            )
                        )
                    )
                    logger.info(f"Calculated streaming cost via litellm: ${cost:.6f}")
                except Exception as e:
                    logger.warning(f"Failed to calculate streaming cost: {e}", exc_info=True)

            # Yield final cost/usage
            if cost > 0.0:
                yield LLMResponse(
                    content="",
                    role="assistant",
                    cost=cost,
                    usage=usage if usage and usage.total_tokens > 0 else None,
                )

        except Exception as e:
            # Enhanced error logging with context
            error_context = {
                "provider_type": self.provider_type,
                "model_name": self.model_name,
                "has_api_key": bool(self.api_key),
                "endpoint_url": self.endpoint_url,
                "error_type": type(e).__name__,
                "error_message": str(e),
                "streaming": True,
            }

            logger.exception(f"Streaming LLM call failed with context: {error_context}")

            # Re-raise with original exception to preserve stack trace
            raise
