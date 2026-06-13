"""Pytest configuration and fixtures for agentarea-agents-sdk tests."""

import os
import sys
import warnings

import pytest

# Add the parent directory to the path so we can import the SDK modules
sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agentarea_agents_sdk"
    ),
)

# Prevent pytest from trying to import the main __init__.py with relative imports
collect_ignore = ["__init__.py"]


class EchoTool:
    """Minimal, side-effect-free BaseTool used as a generic test fixture.

    Replaces the removed eval()-based CalculateTool in tests that only exercise
    the tool registry / executor / agent mechanics rather than calculation.
    """

    @property
    def name(self) -> str:
        return "echo"

    @property
    def description(self) -> str:
        return "Echo back the provided text."

    def get_schema(self) -> dict:
        return {
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string", "description": "Text to echo back"}},
                "required": ["text"],
            }
        }

    def get_openai_function_definition(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                **self.get_schema(),
            },
        }

    async def execute(self, **kwargs) -> dict:
        if "text" not in kwargs:
            return {
                "success": False,
                "result": "No text provided",
                "tool_name": self.name,
                "error": "text is required",
            }
        text = kwargs.get("text", "")
        return {
            "success": True,
            "result": text,
            "tool_name": self.name,
            "error": None,
        }


@pytest.fixture
def echo_tool_cls():
    """Provide the EchoTool class as a safe stand-in test tool."""
    return EchoTool


@pytest.fixture
def test_model():
    """Default model configuration for tests."""
    return "ollama_chat/qwen2.5"


@pytest.fixture
def skip_if_no_llm():
    """Skip test if LLM is not available."""

    def _skip_if_no_llm():
        try:
            from agentarea_agents_sdk.models.llm_model import LLMModel

            LLMModel(provider_type="ollama_chat", model_name="qwen2.5", endpoint_url=None)
            # Try a simple request to check if model is available
            return False  # Don't skip
        except Exception:
            pytest.skip("LLM model not available")

    return _skip_if_no_llm


# Suppress noisy Pydantic serializer warnings coming from LiteLLM provider model types
warnings.filterwarnings(
    "ignore",
    message=r"^Pydantic serializer warnings:",
    category=UserWarning,
    module=r"pydantic\.main",
)
