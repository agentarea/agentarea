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
