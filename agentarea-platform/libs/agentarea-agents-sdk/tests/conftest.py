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
    """Model under test as a litellm ``provider/model`` string.

    Deliberately no default. These tests need *a* model, not a particular
    vendor's, and the default here silently decided which one: the gate probed
    a local Ollama and skipped whenever it was absent, so aiming the suite
    anywhere else meant editing the fixture. Empty means "no model configured",
    which ``skip_if_no_llm`` turns into a skip with an actionable message.
    """
    import os

    return os.getenv("LLM_MODEL", "")


PLACEHOLDER_PROVIDER = "acme_chat"
PLACEHOLDER_MODEL_NAME = "model-x"


@pytest.fixture
def placeholder_model():
    """A ``provider/model`` string naming no real vendor.

    Construction and parsing tests never reach the network. Pinning them to a
    real provider made it look like the behaviour depended on which one, and
    tied them to whatever the real-LLM fixture happened to default to.
    """
    return f"{PLACEHOLDER_PROVIDER}/{PLACEHOLDER_MODEL_NAME}"


@pytest.fixture
def llm_endpoint_url():
    """Base URL for a self-hosted provider (``LLM_API_BASE``), or None if hosted."""
    import os

    return os.getenv("LLM_API_BASE") or None


@pytest.fixture
def skip_if_no_llm(test_model, llm_endpoint_url):
    """Skip the real-LLM tests unless a model is configured and reachable."""

    def _skip_if_no_llm():
        import httpx

        if not test_model:
            pytest.skip("set LLM_MODEL=<provider>/<model> to run the real-LLM tests")

        if llm_endpoint_url:
            # Self-hosted: connectivity is the only thing checked. Any HTTP
            # status means something answered, which is all this gate is for —
            # a 404 on the root is not a reason to skip.
            try:
                httpx.get(llm_endpoint_url, timeout=1.0)
            except httpx.RequestError as exc:
                pytest.skip(f"LLM endpoint {llm_endpoint_url} not reachable: {exc}")

    return _skip_if_no_llm


# Suppress noisy Pydantic serializer warnings coming from LiteLLM provider model types
warnings.filterwarnings(
    "ignore",
    message=r"^Pydantic serializer warnings:",
    category=UserWarning,
    module=r"pydantic\.main",
)
