"""LLM model for encapsulating litellm interactions."""

import logging
from dataclasses import dataclass
from typing import Any, AsyncIterator

import litellm

logger = logging.getLogger(__name__)


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

    def _build_litellm_params(self, request: LLMRequest) -> dict[str, Any]:
        """Build parameters for litellm.acompletion call."""
        litellm_model = f"{self.provider_type}/{self.model_name}"

        params = {
            "model": litellm_model,
            "messages": request.messages,
        }

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

    def _parse_response(self, response) -> LLMResponse:
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
                cost = getattr(response_usage, "total_tokens", 0) * 0.00001  # $0.01 per 1K tokens estimate

        return LLMResponse(
            content=message.content or "",
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
            response = await litellm.acompletion(**params)

            # Parse and return response
            result = self._parse_response(response)
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
                "error_message": str(e)
            }

            logger.error(f"LLM call failed with context: {error_context}")

            # Re-raise with original exception to preserve stack trace
            raise

    async def complete_with_streaming(
        self,
        request: LLMRequest,
        task_id: str,
        agent_id: str,
        execution_id: str,
        event_publisher
    ) -> LLMResponse:
        """Call LLM with streaming and emit chunk events."""
        try:
            # Build parameters for streaming
            params = self._build_litellm_params(request)
            params["stream"] = True

            logger.info(f"Calling LLM with streaming for model {params['model']}")

            # Make the streaming LLM call
            response_stream = await litellm.acompletion(**params)

            # Collect streaming response
            complete_content = ""
            chunk_index = 0
            usage_info = None
            cost = 0.0
            tool_calls = []
            tool_calls_buffer = {}  # Buffer for streaming tool calls

            async for chunk in response_stream:
                if chunk.choices:
                    delta = chunk.choices[0].delta

                    # Handle content chunks
                    if hasattr(delta, 'content') and delta.content:
                        complete_content += delta.content

                        # Emit chunk event
                        if event_publisher:
                            await event_publisher(delta.content, chunk_index, False)

                        chunk_index += 1

                    # Handle tool calls in streaming - proper implementation
                    if hasattr(delta, 'tool_calls') and delta.tool_calls:
                        for tool_call_delta in delta.tool_calls:
                            index = getattr(tool_call_delta, 'index', 0)

                            # Initialize tool call buffer for this index if needed
                            if index not in tool_calls_buffer:
                                tool_calls_buffer[index] = {
                                    "id": "",
                                    "type": "function",
                                    "function": {
                                        "name": "",
                                        "arguments": ""
                                    }
                                }

                            # Update tool call buffer with delta information
                            if hasattr(tool_call_delta, 'id') and tool_call_delta.id:
                                tool_calls_buffer[index]["id"] = tool_call_delta.id

                            if hasattr(tool_call_delta, 'type') and tool_call_delta.type:
                                tool_calls_buffer[index]["type"] = tool_call_delta.type

                            if hasattr(tool_call_delta, 'function') and tool_call_delta.function:
                                function_delta = tool_call_delta.function

                                if hasattr(function_delta, 'name') and function_delta.name:
                                    tool_calls_buffer[index]["function"]["name"] = function_delta.name

                                if hasattr(function_delta, 'arguments') and function_delta.arguments:
                                    tool_calls_buffer[index]["function"]["arguments"] += function_delta.arguments

                # Extract usage and cost from final chunk if available
                if hasattr(chunk, 'usage') and chunk.usage:
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

            logger.info(f"Streaming LLM call completed successfully, cost: ${result.cost:.6f}, chunks: {chunk_index}")
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
                "streaming": True
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

            async for chunk in response_stream:
                if chunk.choices:
                    delta = chunk.choices[0].delta
                    delta_content = ""

                    # Handle content chunks
                    if hasattr(delta, 'content') and delta.content:
                        delta_content = delta.content
                        complete_content += delta_content

                    # Handle tool calls in streaming
                    delta_tool_calls = None
                    if hasattr(delta, 'tool_calls') and delta.tool_calls:
                        for tool_call_delta in delta.tool_calls:
                            index = getattr(tool_call_delta, 'index', 0)

                            # Initialize tool call buffer for this index if needed
                            if index not in tool_calls_buffer:
                                tool_calls_buffer[index] = {
                                    "id": "",
                                    "type": "function",
                                    "function": {
                                        "name": "",
                                        "arguments": ""
                                    }
                                }

                            # Update tool call buffer with delta information
                            if hasattr(tool_call_delta, 'id') and tool_call_delta.id:
                                tool_calls_buffer[index]["id"] = tool_call_delta.id

                            if hasattr(tool_call_delta, 'type') and tool_call_delta.type:
                                tool_calls_buffer[index]["type"] = tool_call_delta.type

                            if hasattr(tool_call_delta, 'function') and tool_call_delta.function:
                                function_delta = tool_call_delta.function

                                if hasattr(function_delta, 'name') and function_delta.name:
                                    tool_calls_buffer[index]["function"]["name"] = function_delta.name

                                if hasattr(function_delta, 'arguments') and function_delta.arguments:
                                    tool_calls_buffer[index]["function"]["arguments"] += function_delta.arguments

                        # For streaming tool calls, return the current state
                        delta_tool_calls = [tool_calls_buffer[i] for i in sorted(tool_calls_buffer.keys())]

                    # Extract usage and cost from chunk if available
                    if hasattr(chunk, 'usage') and chunk.usage:
                        usage_info = chunk.usage
                        # Update usage information
                        usage = LLMUsage(
                            prompt_tokens=getattr(usage_info, "prompt_tokens", 0),
                            completion_tokens=getattr(usage_info, "completion_tokens", 0),
                            total_tokens=getattr(usage_info, "total_tokens", 0),
                        )
                        # Calculate cost
                        if hasattr(usage_info, "completion_tokens_cost"):
                            cost = getattr(usage_info, "completion_tokens_cost", 0.0)
                            if hasattr(usage_info, "prompt_tokens_cost"):
                                cost += getattr(usage_info, "prompt_tokens_cost", 0.0)
                        elif hasattr(usage_info, "total_tokens"):
                            cost = getattr(usage_info, "total_tokens", 0) * 0.00001

                    # Only yield if there's actual content or tool call updates
                    if delta_content or delta_tool_calls or (hasattr(chunk, 'usage') and chunk.usage):
                        yield LLMResponse(
                            content=delta_content,  # Only return the delta content, not accumulated
                            role="assistant",
                            tool_calls=delta_tool_calls,
                            cost=cost,
                            usage=usage,
                        )

            logger.info(f"Streaming LLM call completed successfully, final cost: ${cost:.6f}")

        except Exception as e:
            # Enhanced error logging with context
            error_context = {
                "provider_type": self.provider_type,
                "model_name": self.model_name,
                "has_api_key": bool(self.api_key),
                "endpoint_url": self.endpoint_url,
                "error_type": type(e).__name__,
                "error_message": str(e),
                "streaming": True
            }

            logger.error(f"Streaming LLM call failed with context: {error_context}")

            # Re-raise with original exception to preserve stack trace
            raise