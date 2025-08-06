"""LLM model for encapsulating litellm interactions."""

import logging
from dataclasses import dataclass
from typing import Any

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
        elif self.provider_type == "ollama_chat":
            # Default Ollama URL - use localhost for local development
            params["base_url"] = "http://host.docker.internal:11434"

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
            logger.error(f"LLM call failed: {e!s}")
            raise

