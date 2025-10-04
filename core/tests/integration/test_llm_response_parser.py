#!/usr/bin/env python3
"""
Integration test for LLM model and response parser with ollama_chat/qwen2.5.

Tests the complete LLM integration including:
1. Direct LLM calls with different response modes
2. Response parser functionality
3. Event publishing and streaming
4. Tool call extraction from content vs structured responses
"""

import asyncio
import json
import logging
import subprocess

import pytest

# Setup logging for test visibility
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class EventCapture:
    """Capture events published during streaming."""

    def __init__(self):
        self.events = []

    async def publish_chunk_event(self, chunk: str, chunk_index: int, is_final: bool = False):
        """Capture chunk events."""
        event = {"chunk": chunk, "chunk_index": chunk_index, "is_final": is_final}
        self.events.append(event)
        logger.debug(
            f"Chunk Event: index={chunk_index}, final={is_final}, chunk='{chunk[:30]}{'...' if len(chunk) > 30 else ''}'"
        )


def check_ollama_available():
    """Check if Ollama is running and qwen2.5 is available."""
    try:
        result = subprocess.run(
            ["curl", "-s", "http://localhost:11434/api/tags"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            # Check if qwen2.5 model is available
            response = json.loads(result.stdout)
            models = [model["name"] for model in response.get("models", [])]
            qwen_available = any("qwen2.5" in model for model in models)
            return True, qwen_available
        return False, False
    except Exception:
        return False, False


@pytest.mark.integration
@pytest.mark.asyncio
async def test_llm_with_structured_tools():
    """Test LLM with tools - should return structured tool_calls."""
    ollama_running, qwen_available = check_ollama_available()
    if not ollama_running:
        pytest.skip("Ollama not running on localhost:11434")
    if not qwen_available:
        pytest.skip("qwen2.5 model not available in Ollama")

    from agentarea_agents_sdk.models.llm_model import LLMModel, LLMRequest

    # Initialize LLM model
    llm_model = LLMModel(
        provider_type="ollama_chat",
        model_name="qwen2.5",
        api_key=None,
        endpoint_url="localhost:11434",
    )

    # Messages for task completion
    messages = [
        {
            "role": "system",
            "content": "You are a helpful AI assistant. When you complete a task, call the task_complete function.",
        },
        {
            "role": "user",
            "content": "Please test the task completion functionality. Call task_complete when ready.",
        },
    ]

    # Define tools
    tools = [
        {
            "type": "function",
            "function": {
                "name": "task_complete",
                "description": "Mark task as completed when finished successfully",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "result": {
                            "type": "string",
                            "description": "Optional final result or summary",
                        }
                    },
                    "required": [],
                },
            },
        }
    ]

    request = LLMRequest(messages=messages, tools=tools, temperature=0.7, max_tokens=300)

    # Call LLM
    logger.info("Testing LLM with structured tools...")
    response = await llm_model.complete(request)

    # Assertions
    assert response is not None, "LLM response should not be None"
    assert response.role == "assistant", "Response role should be assistant"
    assert response.cost > 0, "Response should have cost tracking"
    assert response.usage is not None, "Response should have usage information"

    # With tools, expect structured tool calls and empty content
    assert response.tool_calls is not None, "Should have structured tool calls"
    assert len(response.tool_calls) > 0, "Should have at least one tool call"
    assert response.content == "", "Content should be empty when using structured tools"

    # Verify tool call structure
    tool_call = response.tool_calls[0]
    assert tool_call["type"] == "function", "Tool call should be function type"
    assert tool_call["function"]["name"] == "task_complete", "Should call task_complete"
    assert "id" in tool_call, "Tool call should have ID"

    logger.info(f"✅ Structured tools test passed - {len(response.tool_calls)} tool calls")
    return response


@pytest.mark.integration
@pytest.mark.asyncio
async def test_llm_content_based_responses():
    """Test LLM without tools - should return JSON in content."""
    ollama_running, qwen_available = check_ollama_available()
    if not ollama_running:
        pytest.skip("Ollama not running on localhost:11434")
    if not qwen_available:
        pytest.skip("qwen2.5 model not available in Ollama")

    from agentarea_agents_sdk.models.llm_model import LLMModel, LLMRequest

    # Initialize LLM model
    llm_model = LLMModel(
        provider_type="ollama_chat",
        model_name="qwen2.5",
        api_key=None,
        endpoint_url="localhost:11434",
    )

    # Messages requesting JSON format in content
    messages = [
        {
            "role": "system",
            "content": 'You are a helpful AI assistant. When you complete a task, respond with JSON format: {"name": "task_complete", "arguments": {"result": "your result"}}.',
        },
        {
            "role": "user",
            "content": "Please test the task completion functionality. Respond with the JSON format to complete the task.",
        },
    ]

    request = LLMRequest(
        messages=messages,
        tools=None,  # No tools provided
        temperature=0.7,
        max_tokens=300,
    )

    # Call LLM
    logger.info("Testing LLM with content-based responses...")
    response = await llm_model.complete(request)

    # Assertions
    assert response is not None, "LLM response should not be None"
    assert response.role == "assistant", "Response role should be assistant"
    assert response.cost > 0, "Response should have cost tracking"
    assert response.usage is not None, "Response should have usage information"

    # Without tools, expect content with JSON and no structured tool calls
    assert response.tool_calls is None or len(response.tool_calls) == 0, (
        "Should not have structured tool calls"
    )
    assert response.content != "", "Content should not be empty"

    # Verify content contains valid JSON
    try:
        parsed_json = json.loads(response.content)
        assert isinstance(parsed_json, dict), "Content should be valid JSON object"
        assert parsed_json.get("name") == "task_complete", "JSON should contain task_complete call"
        assert "arguments" in parsed_json, "JSON should have arguments field"
    except json.JSONDecodeError:
        pytest.fail(f"Content is not valid JSON: {response.content}")

    logger.info("✅ Content-based test passed - JSON extracted from content")
    return response


@pytest.mark.integration
@pytest.mark.asyncio
async def test_llm_streaming():
    """Test LLM streaming functionality."""
    ollama_running, qwen_available = check_ollama_available()
    if not ollama_running:
        pytest.skip("Ollama not running on localhost:11434")
    if not qwen_available:
        pytest.skip("qwen2.5 model not available in Ollama")

    from agentarea_agents_sdk.models.llm_model import LLMModel, LLMRequest

    # Initialize LLM model
    llm_model = LLMModel(
        provider_type="ollama_chat",
        model_name="qwen2.5",
        api_key=None,
        endpoint_url="localhost:11434",
    )

    # Messages for streaming test
    messages = [
        {"role": "system", "content": "You are a helpful AI assistant. Provide concise responses."},
        {"role": "user", "content": "Explain task completion in AI systems in 2-3 sentences."},
    ]

    request = LLMRequest(messages=messages, tools=None, temperature=0.7, max_tokens=200)

    # Set up event capture
    event_capture = EventCapture()

    # Call LLM with streaming
    logger.info("Testing LLM streaming...")
    response = await llm_model.complete_with_streaming(
        request=request,
        task_id="test-task-123",
        agent_id="test-agent-456",
        execution_id="test-exec-789",
        event_publisher=event_capture.publish_chunk_event,
    )

    # Assertions
    assert response is not None, "Streaming response should not be None"
    assert response.role == "assistant", "Response role should be assistant"
    assert response.content != "", "Streaming should produce content"
    assert len(response.content) > 10, "Response should be meaningful length"
    assert response.cost >= 0, "Response should have cost tracking"

    # Streaming specific assertions
    assert len(event_capture.events) > 0, "Should have captured streaming events"
    assert any(event["is_final"] for event in event_capture.events), "Should have final event"

    # Verify streaming events structure
    for event in event_capture.events:
        assert "chunk" in event, "Event should have chunk"
        assert "chunk_index" in event, "Event should have chunk_index"
        assert "is_final" in event, "Event should have is_final flag"

    logger.info(f"✅ Streaming test passed - {len(event_capture.events)} events captured")
    return response, event_capture.events


@pytest.mark.integration
@pytest.mark.asyncio
async def test_response_parser_with_different_formats():
    """Test our response parser with both structured and content-based responses."""
    ollama_running, qwen_available = check_ollama_available()
    if not ollama_running:
        pytest.skip("Ollama not running on localhost:11434")
    if not qwen_available:
        pytest.skip("qwen2.5 model not available in Ollama")

    import litellm
    from agentarea_execution.parsers.llm_response_parser import LiteLLMResponseParser

    # Test 1: Raw response with structured tool calls
    logger.info("Testing parser with structured tool calls...")
    response1 = await litellm.acompletion(
        model="ollama_chat/qwen2.5",
        messages=[
            {"role": "system", "content": "You are helpful. Call task_complete when done."},
            {"role": "user", "content": "Test task completion. Call the function."},
        ],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "task_complete",
                    "description": "Complete the task",
                    "parameters": {"type": "object", "properties": {}, "required": []},
                },
            }
        ],
        base_url="http://localhost:11434",
    )

    parsed1 = LiteLLMResponseParser.parse_response(response1)

    # Test 2: Raw response with content-based tool calls
    logger.info("Testing parser with content-based tool calls...")
    response2 = await litellm.acompletion(
        model="ollama_chat/qwen2.5",
        messages=[
            {
                "role": "system",
                "content": 'Respond with JSON: {"name": "task_complete", "arguments": {"result": "your result"}}.',
            },
            {"role": "user", "content": "Test completion with JSON format."},
        ],
        base_url="http://localhost:11434",
    )

    parsed2 = LiteLLMResponseParser.parse_response(response2)

    # Assertions for structured response
    assert parsed1["role"] == "assistant", "Parsed response should have assistant role"
    assert parsed1["content"] == "", "Structured response should have empty content"
    assert parsed1["tool_calls"] is not None, "Structured response should have tool calls"
    assert len(parsed1["tool_calls"]) > 0, "Should have extracted tool calls"
    assert parsed1["cost"] >= 0, "Should have cost information"

    # Assertions for content-based response
    assert parsed2["role"] == "assistant", "Parsed response should have assistant role"
    assert parsed2["content"] != "", "Content response should have content"
    assert parsed2["tool_calls"] is not None, "Parser should extract tool calls from content"
    assert len(parsed2["tool_calls"]) > 0, "Should have extracted tool calls from content"
    assert parsed2["cost"] >= 0, "Should have cost information"

    # Verify extracted tool call from content
    extracted_tool = parsed2["tool_calls"][0]
    assert extracted_tool["function"]["name"] == "task_complete", (
        "Should extract task_complete from content"
    )

    logger.info("✅ Response parser test passed - both formats handled correctly")
    return parsed1, parsed2


@pytest.mark.integration
@pytest.mark.asyncio
async def test_react_framework_issue():
    """Test the ReAct framework issue where LLM jumps straight to tool calls."""
    ollama_running, qwen_available = check_ollama_available()
    if not ollama_running:
        pytest.skip("Ollama not running on localhost:11434")
    if not qwen_available:
        pytest.skip("qwen2.5 model not available in Ollama")

    from agentarea_agents_sdk.models.llm_model import LLMModel, LLMRequest

    # Initialize LLM model
    llm_model = LLMModel(
        provider_type="ollama_chat",
        model_name="qwen2.5",
        api_key=None,
        endpoint_url="localhost:11434",
    )

    # ReAct framework messages (similar to what the debug shows)
    messages = [
        {
            "role": "system",
            "content": """You are Test Agent, an AI agent that follows the ReAct (Reasoning + Acting) framework.

You are a helpful assistant that provides clear, natural language responses.

## Current Task
Goal: Tell me a short joke about programming

Success Criteria:
- Provide a programming joke
- Explain why it's funny

## Available Tools
- task_complete: Mark task as completed when all success criteria are met

## ReAct Framework Instructions
You MUST follow this exact pattern for EVERY action you take:

1. **Thought**: First, analyze the current situation and what needs to be done
2. **Observation**: Note what information you have and what you're missing  
3. **Action**: Decide on the next action (tool call or response)
4. **Result**: After a tool call, observe and interpret the results

CRITICAL RULES:
- NEVER call tools without first showing your **Thought** and **Observation**
- NEVER call task_complete without first demonstrating your work step-by-step
- You must show your reasoning process for EVERY action, including the final completion

Continue this pattern until the task is complete, then use the task_complete tool with comprehensive details.

Remember: ALWAYS show your reasoning before taking actions. Users want to see your thought process.""",
        },
        {"role": "user", "content": "Tell me a short joke about programming"},
    ]

    # Tools available
    tools = [
        {
            "type": "function",
            "function": {
                "name": "task_complete",
                "description": "Mark task as completed when all success criteria are met",
                "parameters": {
                    "type": "object",
                    "properties": {"result": {"type": "string", "description": "Final result"}},
                    "required": [],
                },
            },
        }
    ]

    request = LLMRequest(messages=messages, tools=tools, temperature=0.7, max_tokens=500)

    # Call LLM
    logger.info("Testing ReAct framework behavior...")
    response = await llm_model.complete(request)

    # Log the actual response for analysis
    logger.info(f"Response content: {response.content!r}")
    logger.info(f"Tool calls: {len(response.tool_calls) if response.tool_calls else 0}")

    # Analysis assertions
    assert response is not None, "Should get a response"

    # Check if LLM is following ReAct pattern
    if response.tool_calls and not response.content:
        logger.warning("⚠️ LLM jumped straight to tool calls without ReAct reasoning!")
        logger.warning(
            "This indicates the tool_choice or model configuration may be forcing tool usage"
        )

        # This is the problematic behavior we want to identify
        assert False, "LLM should provide reasoning content before calling tools in ReAct framework"

    elif response.content and "**Thought:**" in response.content:
        logger.info("✅ LLM is following ReAct framework properly")
        assert "**Thought:**" in response.content, "Should show reasoning process"

    else:
        logger.info(f"📝 LLM provided natural response: {response.content[:100]}...")
        # This is acceptable - natural language response without forcing ReAct format
        assert len(response.content) > 10, "Should provide meaningful content"

    return response


if __name__ == "__main__":
    """Run tests directly for development/debugging."""

    async def run_all_tests():
        logger.info("🚀 Running LLM Integration Tests")
        logger.info("=" * 60)

        tests = [
            ("Structured Tools", test_llm_with_structured_tools()),
            ("Content-Based", test_llm_content_based_responses()),
            ("Streaming", test_llm_streaming()),
            ("Response Parser", test_response_parser_with_different_formats()),
            ("ReAct Framework", test_react_framework_issue()),
        ]

        results = {}
        for test_name, test_coro in tests:
            try:
                logger.info(f"\n🧪 Running {test_name} test...")
                result = await test_coro
                results[test_name] = True
                logger.info(f"✅ {test_name} test passed")
            except Exception as e:
                results[test_name] = False
                logger.error(f"❌ {test_name} test failed: {e}")

        logger.info("\n📊 Test Results:")
        for test_name, passed in results.items():
            status = "PASSED" if passed else "FAILED"
            logger.info(f"  {test_name}: {status}")

        return results

    # Check Ollama availability
    ollama_running, qwen_available = check_ollama_available()
    if not ollama_running:
        logger.error("❌ Ollama not running on localhost:11434")
        exit(1)
    if not qwen_available:
        logger.error("❌ qwen2.5 model not available. Run: ollama pull qwen2.5")
        exit(1)

    logger.info("✅ Ollama and qwen2.5 available")

    # Run tests
    try:
        results = asyncio.run(run_all_tests())
        if all(results.values()):
            print("\n🎉 ALL TESTS PASSED!")
        else:
            print(f"\n❌ {sum(not v for v in results.values())} TESTS FAILED!")
            exit(1)
    except KeyboardInterrupt:
        logger.info("Tests interrupted by user")
    except Exception as e:
        logger.error(f"Test suite failed: {e}")
        exit(1)
