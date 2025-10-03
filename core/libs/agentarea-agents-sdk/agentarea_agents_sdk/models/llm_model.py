"""LLM model for encapsulating litellm interactions."""

import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

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

logger = logging.getLogger(__name__)

# Configure LiteLLM callbacks via env to avoid noisy defaults during tests
import os  # noqa: E402

_callbacks_env = os.getenv("LITELLM_CALLBACKS")
if _callbacks_env is not None:
    try:
        litellm.callbacks = [cb.strip() for cb in _callbacks_env.split(",") if cb.strip()]
    except Exception:
        litellm.callbacks = []
else:
    # Default to no callbacks unless explicitly configured
    litellm.callbacks = []


@dataclass
class LLMRequest:
    """Request parameters for LLM calls."""

    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]] | None = None
    temperature: float | None = None
    max_tokens: int | None = None


@dataclass
class LLMUsage:
    """Token usage information from LLM response."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class LLMResponse:
    """Standardized LLM response format."""

    content: str
    role: str
    tool_calls: list[dict[str, Any]] | None = None
    cost: float = 0.0
    usage: LLMUsage | None = None


class LLMModel:
    """Encapsulates LLM model logic using litellm."""

    def __init__(
        self,
        provider_type: str,
        model_name: str,
        api_key: str | None = None,
        endpoint_url: str | None = None,
    ):
        """Initialize LLM model with explicit parameters.

        Args:
            provider_type: The LLM provider type (e.g., "openai", "anthropic", "ollama_chat")
            model_name: The model name (e.g., "gpt-3.5-turbo", "claude-3-opus")
            api_key: API key for the provider (optional for local models)
            endpoint_url: Custom endpoint URL (optional, uses provider defaults)
        """
        self.provider_type = provider_type
        self.model_name = model_name
        self.api_key = api_key
        self.endpoint_url = endpoint_url

    def _safe_json_serialize(self, obj: Any) -> str:
        """Convert any Python object to JSON-serializable string safely."""
        try:
            return json.dumps(obj, ensure_ascii=False)
        except (TypeError, OverflowError):
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
                except Exception:  # noqa: S110
                    pass
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
                    except Exception:  # noqa: S110
                        pass
            return {
                "role": "assistant",
                "content": self._to_content_parts(msg.content, msg.metadata),
                **({"tool_calls": tool_calls} if tool_calls else {}),
            }

        # If it's already a dict/list in OpenAI format, return as-is
        if isinstance(msg, dict | list):
            return msg

        # If it's a legacy SDK message dict-like
        if hasattr(msg, "role") and hasattr(msg, "content"):
            return {"role": getattr(msg, "role"), "content": getattr(msg, "content")}

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
        # elif self.provider_type == "ollama_chat":
        # Default Ollama URL - use localhost for local development
        # params["base_url"] = "http://host.docker.internal:11434"

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

    def _parse_response(self, response: ModelResponse) -> LLMResponse:
        """Parse litellm response into standardized format."""
        message = response.choices[0].message

        # Handle tool calls
        tool_calls = None
        if hasattr(message, "tool_calls") and message.tool_calls:
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
            ]
        elif hasattr(message, "function_call") and getattr(message, "function_call"):
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
        cost = 0.0
        usage = LLMUsage()

        if hasattr(response, "usage") and response.usage:
            response_usage = response.usage

            # Update usage statistics
            usage = LLMUsage(
                prompt_tokens=getattr(response_usage, "prompt_tokens", 0),
                completion_tokens=getattr(response_usage, "completion_tokens", 0),
                total_tokens=getattr(response_usage, "total_tokens", 0),
            )

            # litellm includes cost calculation in some cases
            if hasattr(response_usage, "completion_tokens_cost"):
                cost += getattr(response_usage, "completion_tokens_cost", 0.0)
            if hasattr(response_usage, "prompt_tokens_cost"):
                cost += getattr(response_usage, "prompt_tokens_cost", 0.0)
            # Fallback: calculate cost using token counts if available
            elif hasattr(response_usage, "total_tokens"):
                # This is a rough estimate - actual costs vary by model
                # For production, should use model-specific pricing
                cost = (
                    getattr(response_usage, "total_tokens", 0) * 0.00001
                )  # $0.01 per 1K tokens estimate

        # Follow OpenAI standard: when tool_calls are present, content should be minimal
        content = message.content or ""

        return LLMResponse(
            content=content,
            role=message.role,
            tool_calls=tool_calls,
            cost=cost,
            usage=usage,
        )

    async def complete(self, request: LLMRequest) -> LLMResponse:
        """Call LLM with the provided request."""
        try:
            # Build parameters
            params = self._build_litellm_params(request)

            logger.info(f"Calling LLM with model {params['model']}")

            # Make the LLM call
            typed_response: ModelResponse = await acompletion(**params)

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

            logger.error(f"LLM call failed with context: {error_context}")

            # Re-raise with original exception to preserve stack trace
            raise

    async def complete_with_streaming(
        self, request: LLMRequest, task_id: str, agent_id: str, execution_id: str, event_publisher
    ) -> LLMResponse:
        """Call LLM with streaming and emit chunk events."""
        try:
            # Build parameters for streaming
            params = self._build_litellm_params(request)
            params["stream"] = True

            logger.info(f"Calling LLM with streaming for model {params['model']}")

            # Make the streaming LLM call
            response_stream = await acompletion(**params)

            # Collect streaming response
            complete_content = ""
            chunk_index = 0
            usage_info = None
            cost = 0.0
            tool_calls = []
            tool_calls_buffer = {}  # Buffer for streaming tool calls

            async for chunk in response_stream:  # type: ignore[assignment]
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
                    if hasattr(delta, "function_call") and getattr(delta, "function_call"):
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
                # Extract usage and cost from final chunk if available
                if hasattr(chunk, "usage") and chunk.usage:
                    usage_info = chunk.usage
                    # Calculate cost similar to non-streaming version
                    if hasattr(usage_info, "completion_tokens_cost"):
                        cost += getattr(usage_info, "completion_tokens_cost", 0.0)
                    if hasattr(usage_info, "prompt_tokens_cost"):
                        cost += getattr(usage_info, "prompt_tokens_cost", 0.0)
                    elif hasattr(usage_info, "total_tokens"):
                        cost = getattr(usage_info, "total_tokens", 0) * 0.00001

            # Convert tool calls buffer to final format
            if tool_calls_buffer:
                tool_calls = [tool_calls_buffer[i] for i in sorted(tool_calls_buffer.keys())]

            # Emit final chunk event
            if event_publisher:
                await event_publisher("", chunk_index, True)

            # Create usage object
            usage = LLMUsage()
            if usage_info:
                usage = LLMUsage(
                    prompt_tokens=getattr(usage_info, "prompt_tokens", 0),
                    completion_tokens=getattr(usage_info, "completion_tokens", 0),
                    total_tokens=getattr(usage_info, "total_tokens", 0),
                )

            # Return complete response
            result = LLMResponse(
                content=complete_content,
                role="assistant",
                tool_calls=tool_calls,
                cost=cost,
                usage=usage,
            )

            logger.info(
                f"Streaming LLM call completed successfully, cost: ${result.cost:.6f}, chunks: {chunk_index}"
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

            logger.error(f"Streaming LLM call failed with context: {error_context}")

            # Re-raise with original exception to preserve stack trace
            raise

    async def ainvoke_stream(self, request: LLMRequest) -> AsyncIterator[LLMResponse]:
        """Call LLM with streaming and yield responses as they arrive.

        Args:
            request: The LLM request parameters

        Yields:
            LLMResponse objects containing delta responses (only new content)
        """

        try:
            # Build parameters for streaming
            params = self._build_litellm_params(request)
            params["stream"] = True

            logger.info(f"Starting streaming LLM call for model {params['model']}")

            # Make the streaming LLM call
            response_stream = await litellm.acompletion(**params)

            # Process streaming response
            complete_content = ""  # Keep track for tool calls and final usage
            tool_calls_buffer = {}  # Buffer for streaming tool calls
            usage = LLMUsage()
            cost = 0.0

            async for chunk in response_stream:  # type: ignore[assignment]
                # chunk: ModelResponse
                if chunk.choices:
                    delta = chunk.choices[0].delta
                    delta_content = ""
                    delta_tool_calls = None
                    tool_calls_updated = False

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
                    if hasattr(delta, "function_call") and getattr(delta, "function_call"):
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

                # Extract usage and cost from final chunk if available
                if hasattr(chunk, "usage") and chunk.usage:
                    usage_info = chunk.usage
                    # Calculate cost similar to non-streaming version
                    if hasattr(usage_info, "completion_tokens_cost"):
                        cost += getattr(usage_info, "completion_tokens_cost", 0.0)
                    if hasattr(usage_info, "prompt_tokens_cost"):
                        cost += getattr(usage_info, "prompt_tokens_cost", 0.0)
                    elif hasattr(usage_info, "total_tokens"):
                        cost = getattr(usage_info, "total_tokens", 0) * 0.00001

                # Provide current tool call state if updated this chunk
                if tool_calls_updated:
                    delta_tool_calls = [
                        tool_calls_buffer[i] for i in sorted(tool_calls_buffer.keys())
                    ]

                # Yield delta response for each content or tool-calls update
                if (
                    ("delta_content" in locals() and delta_content)
                    or delta_tool_calls is not None
                    or (hasattr(chunk, "usage") and chunk.usage)
                ):
                    # Build usage object only when present on this chunk
                    usage_delta = None
                    if hasattr(chunk, "usage") and chunk.usage:
                        usage_delta = LLMUsage(
                            prompt_tokens=getattr(chunk.usage, "prompt_tokens", 0),
                            completion_tokens=getattr(chunk.usage, "completion_tokens", 0),
                            total_tokens=getattr(chunk.usage, "total_tokens", 0),
                        )
                    yield LLMResponse(
                        content=delta_content if "delta_content" in locals() else "",
                        role="assistant",
                        tool_calls=delta_tool_calls,
                        cost=cost if usage_delta else 0.0,
                        usage=usage_delta,
                    )

            # After streaming ends, yield final message if any remaining content accumulated
            if complete_content and False:  # Explicitly avoid yielding final full content here
                yield LLMResponse(
                    content=complete_content,
                    role="assistant",
                    tool_calls=[tool_calls_buffer[i] for i in sorted(tool_calls_buffer.keys())]
                    if tool_calls_buffer
                    else None,
                    cost=cost,
                    usage=usage,
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

            logger.error(f"Streaming LLM call failed with context: {error_context}")

            # Re-raise with original exception to preserve stack trace
            raise
