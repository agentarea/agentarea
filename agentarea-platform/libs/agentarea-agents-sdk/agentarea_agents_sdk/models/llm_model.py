"""LLM model: one chat call over the transport the provider speaks."""

import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import httpx

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
from .provider_profiles import Transport, profile_for

if TYPE_CHECKING:
    from agentarea_common.utils.url_safety import OutboundPolicy

logger = logging.getLogger(__name__)

# What a caller sees when the outbound policy refuses an endpoint. The guard's own
# message names the address the host resolved to, which would tell a member which
# internal names exist; that detail goes to the log only.
ENDPOINT_REFUSED = "the endpoint URL points to an address this deployment does not call"

# Anthropic requires max_tokens on every request.
ANTHROPIC_DEFAULT_MAX_TOKENS = 4096

# Anthropic reports a failure inside an open stream as an event, not a status.
_ANTHROPIC_STREAM_ERROR_STATUS = {
    "invalid_request_error": 400,
    "authentication_error": 401,
    "permission_error": 403,
    "not_found_error": 404,
    "request_too_large": 413,
    "rate_limit_error": 429,
    "api_error": 500,
    "overloaded_error": 529,
}

ChunkPublisher = Callable[[str, int, bool], Awaitable[Any]]


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
    """Read a provider's usage block, in OpenAI or Anthropic shape.

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


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        )
    return "" if content is None else str(content)


def _anthropic_image(part: dict[str, Any]) -> dict[str, Any]:
    image = part.get("image_url")
    url = image.get("url", "") if isinstance(image, dict) else str(image or "")
    if url.startswith("data:") and ";base64," in url:
        header, data = url.split(",", 1)
        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": header[len("data:") :].split(";", 1)[0],
                "data": data,
            },
        }
    return {"type": "image", "source": {"type": "url", "url": url}}


def _anthropic_blocks(content: Any) -> list[dict[str, Any]]:
    if isinstance(content, str):
        return [{"type": "text", "text": content}] if content else []
    if isinstance(content, dict):
        content = [content]
    if not isinstance(content, list):
        return [{"type": "text", "text": str(content)}] if content is not None else []
    blocks: list[dict[str, Any]] = []
    for part in content:
        if not isinstance(part, dict):
            blocks.append({"type": "text", "text": str(part)})
        elif part.get("type") == "image_url":
            blocks.append(_anthropic_image(part))
        elif part.get("type") == "text":
            if part.get("text"):
                blocks.append({"type": "text", "text": part["text"]})
        else:
            blocks.append(part)
    return blocks


def _anthropic_tool_use(tool_call: dict[str, Any]) -> dict[str, Any]:
    function = tool_call.get("function") or {}
    arguments = function.get("arguments") or "{}"
    try:
        tool_input = json.loads(arguments) if isinstance(arguments, str) else arguments
    except json.JSONDecodeError:
        logger.warning("Tool call %s has arguments that are not JSON", tool_call.get("id"))
        tool_input = {}
    return {
        "type": "tool_use",
        "id": tool_call.get("id", ""),
        "name": function.get("name", ""),
        "input": tool_input if isinstance(tool_input, dict) else {},
    }


def to_anthropic_messages(
    messages: list[dict[str, Any]],
) -> tuple[str | None, list[dict[str, Any]]]:
    """OpenAI-shaped chat messages as Anthropic's ``system`` plus alternating turns.

    Tool results become ``tool_result`` blocks in a user turn, assistant tool calls
    become ``tool_use`` blocks, and consecutive turns of one role are merged, since
    the Messages API accepts only alternating roles.
    """
    system_parts: list[str] = []
    turns: list[dict[str, Any]] = []
    for message in messages:
        role = message.get("role")
        if role == "system":
            text = _text_of(message.get("content"))
            if text:
                system_parts.append(text)
            continue
        if role == "tool":
            content = message.get("content")
            blocks = [
                {
                    "type": "tool_result",
                    "tool_use_id": message.get("tool_call_id", ""),
                    "content": content if isinstance(content, str) else json.dumps(content),
                }
            ]
            role = "user"
        elif role == "assistant":
            blocks = _anthropic_blocks(message.get("content"))
            blocks += [_anthropic_tool_use(tc) for tc in message.get("tool_calls") or []]
        else:
            role = "user"
            blocks = _anthropic_blocks(message.get("content"))
        if not blocks:
            continue
        if turns and turns[-1]["role"] == role:
            turns[-1]["content"].extend(blocks)
        else:
            turns.append({"role": role, "content": blocks})
    return ("\n\n".join(system_parts) or None), turns


def to_anthropic_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """OpenAI function tools as Anthropic tool definitions."""
    converted = []
    for tool in tools:
        function = tool.get("function", tool)
        converted.append(
            {
                "name": function.get("name", ""),
                "description": function.get("description", ""),
                "input_schema": function.get("parameters") or {"type": "object", "properties": {}},
            }
        )
    return converted


class LLMModel:
    """One model at one provider, called over the transport its profile names."""

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
            provider_type: The provider type (e.g., "openai", "anthropic", "ollama_chat")
            model_name: The model name (e.g., "gpt-4.1", "claude-sonnet-4-5")
            api_key: API key for the provider (optional for local models)
            endpoint_url: Custom endpoint URL; the provider's public address otherwise.
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
        self._profile = profile_for(provider_type)

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
        """Return content in the OpenAI chat shape:
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
        """Normalize an SDK message or dict to an OpenAI chat message dict.
        - Assistant tool_calls kept in the OpenAI function-call shape
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

    def _api_url(self, path: str) -> str:
        url = self._profile.resolve_api_url(self.endpoint_url, path)
        if url is None:
            raise ValueError(
                f"Provider {self.provider_type!r} has no public address and no "
                "endpoint_url is configured"
            )
        return url

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

    def _stream(self, request: LLMRequest) -> AsyncIterator[LLMResponse]:
        if self._profile.transport is Transport.ANTHROPIC:
            return self._stream_anthropic(request)
        return self._stream_openai_compatible(request)

    async def _stream_openai_compatible(self, request: LLMRequest) -> AsyncIterator[LLMResponse]:
        """Stream from an OpenAI-compatible ``/chat/completions`` endpoint."""
        url = self._api_url("/chat/completions")

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

        headers: dict[str, str] = {
            "Content-Type": "application/json",
            **self._profile.build_headers(self.api_key),
        }

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

                    # Extract tool calls; some providers still stream the legacy function_call
                    delta_tool_calls = None
                    tool_call_deltas = delta.get("tool_calls") or (
                        [{"index": 0, "function": delta["function_call"]}]
                        if delta.get("function_call")
                        else None
                    )
                    if tool_call_deltas:
                        for tc_delta in tool_call_deltas:
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

    async def _stream_anthropic(self, request: LLMRequest) -> AsyncIterator[LLMResponse]:
        """Stream from Anthropic's Messages API, yielding the same deltas as the OpenAI path."""
        url = self._api_url("/messages")
        system, turns = to_anthropic_messages(self._normalize_messages(request.messages))

        payload: dict[str, Any] = {
            "model": self.model_name,
            "messages": turns,
            "max_tokens": request.max_tokens or ANTHROPIC_DEFAULT_MAX_TOKENS,
            "stream": True,
        }
        if system:
            payload["system"] = system
        if request.tools:
            payload["tools"] = to_anthropic_tools(request.tools)
            payload["tool_choice"] = {"type": "auto"}
        if request.temperature is not None:
            payload["temperature"] = request.temperature

        headers: dict[str, str] = {
            "Content-Type": "application/json",
            **self._profile.build_headers(self.api_key),
        }

        usage_fields: dict[str, Any] = {}
        tool_calls: list[dict[str, Any]] = []
        tool_at_block: dict[int, dict[str, Any]] = {}

        async with self._http_client(httpx.Timeout(300.0)) as client:
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
                    try:
                        event = json.loads(line[5:].strip())
                    except json.JSONDecodeError:
                        continue
                    kind = event.get("type")

                    if kind == "message_start":
                        usage_fields.update(event.get("message", {}).get("usage") or {})
                    elif kind == "content_block_start":
                        block = event.get("content_block") or {}
                        if block.get("type") == "tool_use":
                            call = {
                                "id": block.get("id", ""),
                                "type": "function",
                                "function": {"name": block.get("name", ""), "arguments": ""},
                            }
                            tool_calls.append(call)
                            tool_at_block[event.get("index", len(tool_calls) - 1)] = call
                            yield LLMResponse(content="", role="assistant", tool_calls=tool_calls)
                    elif kind == "content_block_delta":
                        delta = event.get("delta") or {}
                        delta_type = delta.get("type")
                        if delta_type == "text_delta" and delta.get("text"):
                            yield LLMResponse(content=delta["text"], role="assistant")
                        elif delta_type == "thinking_delta" and delta.get("thinking"):
                            yield LLMResponse(
                                content="", role="assistant", reasoning_content=delta["thinking"]
                            )
                        elif delta_type == "input_json_delta" and delta.get("partial_json"):
                            call = tool_at_block.get(event.get("index", -1))
                            if call is not None:
                                call["function"]["arguments"] += delta["partial_json"]
                                yield LLMResponse(
                                    content="", role="assistant", tool_calls=tool_calls
                                )
                    elif kind == "message_delta":
                        usage_fields.update(event.get("usage") or {})
                    elif kind == "error":
                        error = event.get("error") or {}
                        raise LLMProviderHTTPError(
                            _ANTHROPIC_STREAM_ERROR_STATUS.get(error.get("type", ""), 500),
                            str(error.get("message", "stream error")),
                        )
                    elif kind == "message_stop":
                        break
            finally:
                await resp.aclose()

        if usage_fields:
            usage = usage_from_provider(usage_fields)
            yield LLMResponse(
                content="",
                role="assistant",
                cost=self._configured_cost(usage),
                usage=usage,
            )

    async def _complete_from_stream(
        self, request: LLMRequest, event_publisher: ChunkPublisher | None = None
    ) -> LLMResponse:
        content: list[str] = []
        reasoning: list[str] = []
        tool_calls: list[dict[str, Any]] | None = None
        usage: LLMUsage | None = None
        cost = Decimal(0)
        async for chunk in self._stream(request):
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

    def _log_failure(self, error: Exception, *, streaming: bool) -> None:
        error_context = {
            "provider_type": self.provider_type,
            "model_name": self.model_name,
            "has_api_key": bool(self.api_key),
            "endpoint_url": self.endpoint_url,
            "error_type": type(error).__name__,
            "error_message": str(error),
            "streaming": streaming,
        }
        logger.exception(f"LLM call failed with context: {error_context}")

    async def complete(self, request: LLMRequest) -> LLMResponse:
        """Call LLM with the provided request."""
        try:
            result = await self._complete_from_stream(request)
        except Exception as e:
            self._log_failure(e, streaming=False)
            raise
        logger.info(f"LLM call completed successfully, cost: ${result.cost:.6f}")
        return result

    async def complete_with_streaming(
        self,
        request: LLMRequest,
        task_id: str,
        agent_id: str,
        execution_id: str,
        event_publisher: ChunkPublisher | None,
    ) -> LLMResponse:
        """Call LLM with streaming and emit chunk events."""
        try:
            result = await self._complete_from_stream(request, event_publisher)
        except Exception as e:
            self._log_failure(e, streaming=True)
            raise
        logger.info(f"Streaming LLM call completed successfully, cost: ${result.cost:.6f}")
        return result

    async def ainvoke_stream(self, request: LLMRequest) -> AsyncIterator[LLMResponse]:
        """Call LLM with streaming and yield responses as they arrive.

        Yields:
            LLMResponse objects containing delta responses (only new content); the
            last one carrying usage holds the call's cost.
        """
        try:
            async for response in self._stream(request):
                yield response
        except Exception as e:
            self._log_failure(e, streaming=True)
            raise
