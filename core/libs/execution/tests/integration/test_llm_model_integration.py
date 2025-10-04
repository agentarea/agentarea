"""Integration tests for LLM model with real Ollama instance.

These tests require:
- Ollama running on localhost:11434
- qwen2.5 model available in Ollama

Run with: pytest libs/execution/tests/integration/test_llm_model_integration.py -v -s
"""

import asyncio
import json
import logging
import subprocess
import sys
from typing import Any
from uuid import uuid4

import pytest
from agentarea_agents_sdk.models.llm_model import LLMModel, LLMRequest, LLMResponse, LLMUsage

# Configure logging for test output with proper formatting
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# Also configure the LLM model logger
llm_logger = logging.getLogger("agentarea_execution.agentic.models.llm_model")
llm_logger.setLevel(logging.INFO)


class EventCapture:
    """Helper class to capture streaming events during tests."""

    def __init__(self):
        self.events: list[dict[str, Any]] = []
        self.chunks: list[str] = []
        self.event_metadata: dict[str, Any] = {}
        self.total_events = 0
        self.content_events = 0
        self.final_events = 0

    async def publish_chunk_event(self, chunk: str, chunk_index: int, is_final: bool = False):
        """Capture chunk events from streaming LLM calls."""
        import time

        event = {
            "chunk": chunk,
            "chunk_index": chunk_index,
            "is_final": is_final,
            "timestamp": time.time(),
            "chunk_length": len(chunk) if chunk else 0,
        }

        self.events.append(event)
        self.total_events += 1

        if chunk:  # Only add non-empty chunks
            self.chunks.append(chunk)
            self.content_events += 1

        if is_final:
            self.final_events += 1

        # Enhanced logging with more details
        chunk_preview = chunk[:50] + "..." if chunk and len(chunk) > 50 else chunk
        logger.info(
            f"📨 Event {self.total_events}: chunk_idx={chunk_index}, final={is_final}, len={len(chunk) if chunk else 0}"
        )
        if chunk:
            logger.info(f"    Content: '{chunk_preview}'")

    def get_full_content(self) -> str:
        """Reconstruct full content from chunks."""
        return "".join(self.chunks)

    def get_event_summary(self) -> dict[str, Any]:
        """Get summary of captured events."""
        return {
            "total_events": self.total_events,
            "content_events": self.content_events,
            "final_events": self.final_events,
            "total_content_length": len(self.get_full_content()),
            "chunk_sizes": [len(chunk) for chunk in self.chunks],
            "event_timeline": [
                {
                    "index": e["chunk_index"],
                    "is_final": e["is_final"],
                    "content_length": e["chunk_length"],
                }
                for e in self.events
            ],
        }

    def clear(self):
        """Clear captured events."""
        self.events.clear()
        self.chunks.clear()
        self.total_events = 0
        self.content_events = 0
        self.final_events = 0
        self.event_metadata.clear()


@pytest.fixture(scope="session")
def check_ollama_availability():
    """Check if Ollama is running and qwen2.5 model is available."""
    try:
        # Check if Ollama is running
        result = subprocess.run(
            ["curl", "-s", "http://localhost:11434/api/tags"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode != 0:
            pytest.skip("Ollama is not running on localhost:11434")

        # Check if qwen2.5 model is available
        try:
            response_data = json.loads(result.stdout)
            models = [model.get("name", "") for model in response_data.get("models", [])]
            if not any("qwen2.5" in model for model in models):
                pytest.skip(
                    "qwen2.5 model not found in Ollama. Available models: " + ", ".join(models)
                )
        except (json.JSONDecodeError, KeyError):
            logger.warning("Could not parse Ollama models list, proceeding with test")

        logger.info("✅ Ollama is running with qwen2.5 model available")
        return True

    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        pytest.skip(f"Could not check Ollama availability: {e}")


@pytest.fixture
def llm_model():
    """Create LLM model instance for testing."""
    return LLMModel(
        provider_type="ollama_chat",
        model_name="qwen2.5",
        api_key=None,
        endpoint_url="localhost:11434",
    )


@pytest.fixture
def event_capture():
    """Create event capture instance for streaming tests."""
    return EventCapture()


@pytest.mark.integration
class TestLLMModelIntegration:
    """Integration tests for LLM model with real Ollama instance."""

    @pytest.mark.asyncio
    async def test_basic_completion(self, llm_model: LLMModel, check_ollama_availability):
        """Test basic LLM completion without tools."""
        logger.info("🧪 Testing basic LLM completion")

        request = LLMRequest(
            messages=[
                {"role": "system", "content": "You are a helpful assistant. Be concise."},
                {"role": "user", "content": "What is 2 + 2? Answer with just the number."},
            ],
            temperature=0.1,
            max_tokens=50,
        )

        response = await llm_model.complete(request)

        # Assertions
        assert isinstance(response, LLMResponse)
        assert response.content is not None
        assert len(response.content.strip()) > 0
        assert response.role == "assistant"
        assert response.tool_calls is None or len(response.tool_calls) == 0
        assert response.cost >= 0
        assert isinstance(response.usage, LLMUsage)
        assert response.usage.total_tokens > 0

        logger.info(f"✅ Response: {response.content.strip()}")
        logger.info(f"💰 Cost: ${response.cost:.6f}")
        logger.info(f"📊 Usage: {response.usage.total_tokens} tokens")

    @pytest.mark.asyncio
    async def test_completion_with_tools(self, llm_model: LLMModel, check_ollama_availability):
        """Test LLM completion with tool calls."""
        logger.info("🧪 Testing LLM completion with tools")

        tools = [
            {
                "type": "function",
                "function": {
                    "name": "calculate",
                    "description": "Perform mathematical calculations",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "expression": {
                                "type": "string",
                                "description": "Mathematical expression to evaluate",
                            }
                        },
                        "required": ["expression"],
                    },
                },
            }
        ]

        request = LLMRequest(
            messages=[
                {
                    "role": "system",
                    "content": "You are a helpful assistant. Use the calculate function for math problems.",
                },
                {"role": "user", "content": "Calculate 15 * 7 using the calculate function."},
            ],
            tools=tools,
            temperature=0.1,
            max_tokens=200,
        )

        response = await llm_model.complete(request)

        # Assertions
        assert isinstance(response, LLMResponse)
        assert response.role == "assistant"
        assert response.cost >= 0
        assert isinstance(response.usage, LLMUsage)

        # Check if tool calls were made (some models might not support tools perfectly)
        if response.tool_calls:
            assert len(response.tool_calls) > 0
            tool_call = response.tool_calls[0]
            assert "id" in tool_call
            assert "function" in tool_call
            assert tool_call["function"]["name"] == "calculate"
            logger.info(f"✅ Tool call made: {tool_call['function']['name']}")
            logger.info(f"📝 Arguments: {tool_call['function']['arguments']}")
        else:
            # If no tool calls, at least check that content mentions calculation
            assert response.content is not None
            logger.info(f"ℹ️ No tool calls, but got content: {response.content[:100]}...")

        logger.info(f"💰 Cost: ${response.cost:.6f}")
        logger.info(f"📊 Usage: {response.usage.total_tokens} tokens")

    @pytest.mark.asyncio
    async def test_streaming_completion(
        self, llm_model: LLMModel, event_capture: EventCapture, check_ollama_availability
    ):
        """Test LLM completion with streaming and comprehensive event capture."""
        logger.info("🧪 Testing LLM streaming completion with event publisher")

        # Clear any previous events
        event_capture.clear()

        # Create test identifiers
        task_id = "test-task-" + str(uuid4())
        agent_id = "test-agent-" + str(uuid4())
        execution_id = "test-exec-" + str(uuid4())

        logger.info("📋 Test identifiers:")
        logger.info(f"    Task ID: {task_id}")
        logger.info(f"    Agent ID: {agent_id}")
        logger.info(f"    Execution ID: {execution_id}")

        request = LLMRequest(
            messages=[
                {
                    "role": "system",
                    "content": "You are a helpful assistant. Provide detailed explanations.",
                },
                {
                    "role": "user",
                    "content": "Explain what artificial intelligence is in 2-3 sentences.",
                },
            ],
            temperature=0.3,
            max_tokens=150,
        )

        logger.info("🚀 Starting streaming LLM call...")
        response = await llm_model.complete_with_streaming(
            request=request,
            task_id=task_id,
            agent_id=agent_id,
            execution_id=execution_id,
            event_publisher=event_capture.publish_chunk_event,
        )

        logger.info("✅ Streaming call completed, analyzing results...")

        # Get event summary for detailed analysis
        event_summary = event_capture.get_event_summary()

        # Assertions
        assert isinstance(response, LLMResponse)
        assert response.content is not None
        assert len(response.content.strip()) > 0
        assert response.role == "assistant"
        assert response.cost >= 0
        assert isinstance(response.usage, LLMUsage)

        # Check streaming events
        assert len(event_capture.events) > 0, "No events were captured during streaming"
        assert event_summary["total_events"] > 0, "No total events recorded"

        # Check that we have a final event
        final_events = [e for e in event_capture.events if e["is_final"]]
        assert len(final_events) == 1, f"Expected exactly 1 final event, got {len(final_events)}"
        assert event_summary["final_events"] == 1, "Event summary shows incorrect final event count"

        # Verify content reconstruction
        reconstructed_content = event_capture.get_full_content()
        assert reconstructed_content == response.content, (
            "Reconstructed content doesn't match response content"
        )

        # Detailed logging of results
        logger.info("📊 Event Publisher Test Results:")
        logger.info(f"    Total events captured: {event_summary['total_events']}")
        logger.info(f"    Content events: {event_summary['content_events']}")
        logger.info(f"    Final events: {event_summary['final_events']}")
        logger.info(f"    Total content length: {event_summary['total_content_length']} chars")
        logger.info(
            f"    Average chunk size: {sum(event_summary['chunk_sizes']) / len(event_summary['chunk_sizes']) if event_summary['chunk_sizes'] else 0:.1f} chars"
        )

        logger.info(f"✅ Streaming response: {response.content[:100]}...")
        logger.info(f"📨 Event timeline: {len(event_capture.events)} events total")

        # Log first few and last few events for verification
        for i, event in enumerate(event_capture.events[:3]):
            logger.info(
                f"    Event {i + 1}: idx={event['chunk_index']}, final={event['is_final']}, len={event['chunk_length']}"
            )

        if len(event_capture.events) > 6:
            logger.info("    ... (middle events omitted) ...")
            for i, event in enumerate(event_capture.events[-3:], len(event_capture.events) - 2):
                logger.info(
                    f"    Event {i}: idx={event['chunk_index']}, final={event['is_final']}, len={event['chunk_length']}"
                )

        logger.info(f"💰 Cost: ${response.cost:.6f}")
        logger.info(f"📊 Usage: {response.usage.total_tokens} tokens")

        # Additional assertions for event publisher functionality
        assert event_summary["content_events"] > 0, "No content events were captured"
        assert event_summary["total_content_length"] > 0, "No content was captured through events"

        # Verify event ordering
        chunk_indices = [e["chunk_index"] for e in event_capture.events]
        assert chunk_indices == sorted(chunk_indices), (
            "Events are not in correct chronological order"
        )

    @pytest.mark.asyncio
    async def test_event_publisher_comprehensive(
        self, llm_model: LLMModel, event_capture: EventCapture, check_ollama_availability
    ):
        """Comprehensive test of event publisher functionality with different scenarios."""
        logger.info("🧪 Testing comprehensive event publisher functionality")

        # Test 1: Short response with minimal chunks
        logger.info("📝 Test 1: Short response")
        event_capture.clear()

        short_request = LLMRequest(
            messages=[
                {"role": "system", "content": "Be very brief."},
                {"role": "user", "content": "Say just 'Hello'"},
            ],
            temperature=0.1,
            max_tokens=10,
        )

        response1 = await llm_model.complete_with_streaming(
            request=short_request,
            task_id="short-test-" + str(uuid4()),
            agent_id="test-agent",
            execution_id="test-exec",
            event_publisher=event_capture.publish_chunk_event,
        )

        short_summary = event_capture.get_event_summary()
        logger.info(f"    Short response events: {short_summary['total_events']}")
        logger.info(f"    Content: '{response1.content}'")
        assert short_summary["final_events"] == 1
        assert response1.content == event_capture.get_full_content()

        # Test 2: Longer response with more chunks
        logger.info("📝 Test 2: Longer response")
        event_capture.clear()

        long_request = LLMRequest(
            messages=[
                {"role": "system", "content": "Provide detailed explanations."},
                {"role": "user", "content": "Explain the concept of machine learning in detail."},
            ],
            temperature=0.5,
            max_tokens=300,
        )

        response2 = await llm_model.complete_with_streaming(
            request=long_request,
            task_id="long-test-" + str(uuid4()),
            agent_id="test-agent",
            execution_id="test-exec",
            event_publisher=event_capture.publish_chunk_event,
        )

        long_summary = event_capture.get_event_summary()
        logger.info(f"    Long response events: {long_summary['total_events']}")
        logger.info(f"    Content length: {len(response2.content)} chars")
        logger.info(
            f"    Average chunk size: {sum(long_summary['chunk_sizes']) / len(long_summary['chunk_sizes']) if long_summary['chunk_sizes'] else 0:.1f}"
        )

        assert long_summary["final_events"] == 1
        assert response2.content == event_capture.get_full_content()
        assert long_summary["total_events"] > short_summary["total_events"], (
            "Longer response should have more events"
        )

        # Test 3: Event publisher with None (should not crash)
        logger.info("📝 Test 3: No event publisher")

        response3 = await llm_model.complete_with_streaming(
            request=short_request,
            task_id="no-events-" + str(uuid4()),
            agent_id="test-agent",
            execution_id="test-exec",
            event_publisher=None,  # No event publisher
        )

        assert isinstance(response3, LLMResponse)
        assert response3.content is not None
        logger.info(f"    No-events response: '{response3.content}'")

        # Test 4: Event timing and ordering verification
        logger.info("📝 Test 4: Event timing and ordering")
        event_capture.clear()

        timing_request = LLMRequest(
            messages=[{"role": "user", "content": "Count from 1 to 5"}],
            temperature=0.1,
            max_tokens=50,
        )

        import time

        start_time = time.time()

        response4 = await llm_model.complete_with_streaming(
            request=timing_request,
            task_id="timing-test-" + str(uuid4()),
            agent_id="test-agent",
            execution_id="test-exec",
            event_publisher=event_capture.publish_chunk_event,
        )

        end_time = time.time()
        timing_summary = event_capture.get_event_summary()

        # Verify event timestamps are within the call duration
        for event in event_capture.events:
            assert start_time <= event["timestamp"] <= end_time, (
                "Event timestamp outside call duration"
            )

        # Verify events are in chronological order
        timestamps = [e["timestamp"] for e in event_capture.events]
        assert timestamps == sorted(timestamps), "Events not in chronological order"

        logger.info(f"    Timing test completed in {end_time - start_time:.2f}s")
        logger.info(f"    Events captured: {timing_summary['total_events']}")
        logger.info(f"    Response: '{response4.content}'")

        logger.info("✅ All event publisher tests completed successfully")

    @pytest.mark.asyncio
    async def test_error_handling_invalid_model(self, check_ollama_availability):
        """Test error handling with invalid model name."""
        logger.info("🧪 Testing error handling with invalid model")

        llm_model = LLMModel(
            provider_type="ollama_chat",
            model_name="nonexistent-model",
            api_key=None,
            endpoint_url="localhost:11434",
        )

        request = LLMRequest(messages=[{"role": "user", "content": "Hello"}])

        with pytest.raises(Exception) as exc_info:
            await llm_model.complete(request)

        # Verify that the exception contains useful information
        error_str = str(exc_info.value)
        assert len(error_str) > 0
        logger.info(f"✅ Expected error caught: {error_str[:100]}...")

    @pytest.mark.asyncio
    async def test_error_handling_invalid_endpoint(self, check_ollama_availability):
        """Test error handling with invalid endpoint."""
        logger.info("🧪 Testing error handling with invalid endpoint")

        llm_model = LLMModel(
            provider_type="ollama_chat",
            model_name="qwen2.5",
            api_key=None,
            endpoint_url="localhost:99999",  # Invalid port
        )

        request = LLMRequest(messages=[{"role": "user", "content": "Hello"}])

        with pytest.raises(Exception) as exc_info:
            await llm_model.complete(request)

        error_str = str(exc_info.value)
        assert len(error_str) > 0
        logger.info(f"✅ Expected error caught: {error_str[:100]}...")

    @pytest.mark.asyncio
    async def test_parameter_validation(self, llm_model: LLMModel, check_ollama_availability):
        """Test that LLM model handles various parameter combinations."""
        logger.info("🧪 Testing parameter validation")

        # Test with different temperature values
        for temp in [0.0, 0.5, 1.0]:
            request = LLMRequest(
                messages=[{"role": "user", "content": "Say 'hello'"}],
                temperature=temp,
                max_tokens=20,
            )

            response = await llm_model.complete(request)
            assert isinstance(response, LLMResponse)
            assert response.content is not None
            logger.info(f"✅ Temperature {temp}: {response.content.strip()}")

        # Test with different max_tokens
        for max_tokens in [10, 50, 100]:
            request = LLMRequest(
                messages=[{"role": "user", "content": "Count from 1 to 20"}],
                temperature=0.1,
                max_tokens=max_tokens,
            )

            response = await llm_model.complete(request)
            assert isinstance(response, LLMResponse)
            assert response.content is not None
            # Response should be shorter with lower max_tokens
            logger.info(f"✅ Max tokens {max_tokens}: {len(response.content)} chars")

    @pytest.mark.asyncio
    async def test_concurrent_requests(self, llm_model: LLMModel, check_ollama_availability):
        """Test that LLM model handles concurrent requests properly."""
        logger.info("🧪 Testing concurrent requests")

        async def make_request(query: str) -> LLMResponse:
            request = LLMRequest(
                messages=[{"role": "user", "content": query}], temperature=0.1, max_tokens=50
            )
            return await llm_model.complete(request)

        # Make multiple concurrent requests
        queries = ["What is 1 + 1?", "What is 2 + 2?", "What is 3 + 3?"]

        responses = await asyncio.gather(*[make_request(q) for q in queries])

        # Verify all responses
        assert len(responses) == len(queries)
        for i, response in enumerate(responses):
            assert isinstance(response, LLMResponse)
            assert response.content is not None
            assert len(response.content.strip()) > 0
            logger.info(f"✅ Concurrent request {i + 1}: {response.content.strip()}")
