"""Test real LLM tool calls with Ollama/qwen2.5 to identify malformed response source."""

import json
import logging
import os

import pytest
from agentarea_agents_sdk.models.llm_model import LLMModel, LLMRequest

logger = logging.getLogger(__name__)


@pytest.mark.asyncio
async def test_ollama_qwen25_tool_calls_direct():
    """Test direct LLM calls with Ollama/qwen2.5 to see raw responses."""

    # Skip if no Ollama available
    docker_host = os.environ.get("LLM_DOCKER_HOST", "localhost")
    endpoint_url = f"http://{docker_host}:11434"

    logger.info(f"Testing Ollama at {endpoint_url}")

    # Create LLM model
    llm_model = LLMModel(
        provider_type="ollama_chat", model_name="qwen2.5", endpoint_url=endpoint_url
    )

    # Define tools (same as production)
    tools = [
        {
            "type": "function",
            "function": {
                "name": "task_complete",
                "description": "Mark task as completed when you have finished the task successfully. Call this when you're done.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "result": {
                            "type": "string",
                            "description": "Optional final result or summary of what was accomplished",
                        }
                    },
                    "required": [],
                },
            },
        }
    ]

    # Test messages
    messages = [
        {
            "role": "system",
            "content": "You are a helpful AI assistant. When you complete a task, use the task_complete tool.",
        },
        {
            "role": "user",
            "content": "Please complete this simple test task by calling the task_complete tool.",
        },
    ]

    request = LLMRequest(messages=messages, tools=tools, temperature=0.1, max_tokens=100)

    logger.info("=== Testing Non-Streaming LLM Call ===")
    try:
        response = await llm_model.complete(request)

        logger.info("Non-streaming response:")
        logger.info(f"  Content: {response.content}")
        logger.info(f"  Tool calls: {response.tool_calls}")
        logger.info(f"  Role: {response.role}")
        logger.info(f"  Cost: {response.cost}")

        if response.tool_calls:
            for i, tool_call in enumerate(response.tool_calls):
                logger.info(f"  Tool call {i}: {tool_call}")
        else:
            logger.warning("No tool calls in non-streaming response!")

    except Exception as e:
        logger.error(f"Non-streaming call failed: {e}")
        pytest.skip(f"Ollama not available: {e}")

    logger.info("\n=== Testing Streaming LLM Call ===")
    try:
        # Test streaming
        complete_content = ""
        complete_tool_calls = None
        chunk_count = 0

        async for chunk in llm_model.ainvoke_stream(request):
            chunk_count += 1
            logger.info(f"Chunk {chunk_count}:")
            logger.info(f"  Content: '{chunk.content}'")
            logger.info(f"  Tool calls: {chunk.tool_calls}")
            logger.info(f"  Role: {chunk.role}")

            if chunk.content:
                complete_content += chunk.content

            if chunk.tool_calls:
                complete_tool_calls = chunk.tool_calls

        logger.info("\nStreaming summary:")
        logger.info(f"  Total chunks: {chunk_count}")
        logger.info(f"  Complete content: '{complete_content}'")
        logger.info(f"  Final tool calls: {complete_tool_calls}")

        # Check if we have the malformed response issue
        if not complete_tool_calls and complete_content:
            logger.warning("🚨 MALFORMED RESPONSE DETECTED!")
            logger.warning(f"Tool calls are None but content contains: {complete_content}")

            # Try to parse content as JSON
            try:
                parsed = json.loads(complete_content.strip())
                if isinstance(parsed, dict) and "name" in parsed:
                    logger.warning(f"Content appears to be a tool call: {parsed}")
            except json.JSONDecodeError:
                logger.info("Content is not valid JSON")

    except Exception as e:
        logger.error(f"Streaming call failed: {e}")


@pytest.mark.asyncio
async def test_ollama_qwen25_various_prompts():
    """Test various prompts to see when malformed responses occur."""

    docker_host = os.environ.get("LLM_DOCKER_HOST", "localhost")
    endpoint_url = f"http://{docker_host}:11434"

    llm_model = LLMModel(
        provider_type="ollama_chat", model_name="qwen2.5", endpoint_url=endpoint_url
    )

    tools = [
        {
            "type": "function",
            "function": {
                "name": "task_complete",
                "description": "Mark task as completed",
                "parameters": {
                    "type": "object",
                    "properties": {"result": {"type": "string", "description": "Result"}},
                    "required": [],
                },
            },
        }
    ]

    test_cases = [
        {
            "name": "Simple completion request",
            "messages": [
                {"role": "user", "content": "Complete this task using the task_complete tool."}
            ],
        },
        {"name": "Vague task (like production)", "messages": [{"role": "user", "content": "test"}]},
        {
            "name": "Explicit tool instruction",
            "messages": [
                {"role": "system", "content": "You must use the task_complete tool when done."},
                {"role": "user", "content": "Do a simple task and complete it."},
            ],
        },
    ]

    for test_case in test_cases:
        logger.info(f"\n=== Testing: {test_case['name']} ===")

        request = LLMRequest(
            messages=test_case["messages"], tools=tools, temperature=0.1, max_tokens=150
        )

        try:
            # Test streaming response
            complete_content = ""
            complete_tool_calls = None

            async for chunk in llm_model.ainvoke_stream(request):
                if chunk.content:
                    complete_content += chunk.content
                if chunk.tool_calls:
                    complete_tool_calls = chunk.tool_calls

            logger.info("Result:")
            logger.info(f"  Content: '{complete_content}'")
            logger.info(f"  Tool calls: {complete_tool_calls}")

            # Analyze the response
            if not complete_tool_calls and complete_content:
                # Check if content looks like a tool call
                if "task_complete" in complete_content.lower():
                    logger.warning("🚨 MALFORMED: Tool call in content, not tool_calls field")

                    # Try to extract JSON
                    try:
                        # Look for JSON patterns
                        import re

                        json_pattern = r'\{[^}]*"name"[^}]*\}'
                        matches = re.findall(json_pattern, complete_content)
                        if matches:
                            logger.warning(f"Found JSON patterns: {matches}")
                    except Exception as e:
                        logger.debug(f"JSON extraction failed: {e}")

        except Exception as e:
            logger.error(f"Test case '{test_case['name']}' failed: {e}")


@pytest.mark.asyncio
async def test_litellm_direct_ollama():
    """Test litellm directly to see if the issue is in our wrapper or litellm itself."""

    import litellm

    docker_host = os.environ.get("LLM_DOCKER_HOST", "localhost")
    base_url = f"http://{docker_host}:11434"

    logger.info(f"=== Testing litellm directly with Ollama at {base_url} ===")

    tools = [
        {
            "type": "function",
            "function": {
                "name": "task_complete",
                "description": "Mark task as completed",
                "parameters": {
                    "type": "object",
                    "properties": {"result": {"type": "string", "description": "Result"}},
                    "required": [],
                },
            },
        }
    ]

    messages = [{"role": "user", "content": "Complete this task using the task_complete tool."}]

    try:
        # Test non-streaming
        logger.info("Non-streaming litellm call:")
        response = await litellm.acompletion(
            model="ollama_chat/qwen2.5",
            messages=messages,
            tools=tools,
            base_url=base_url,
            temperature=0.1,
            max_tokens=100,
        )

        message = response.choices[0].message
        logger.info(f"  Content: '{message.content}'")
        logger.info(f"  Tool calls: {getattr(message, 'tool_calls', None)}")

        # Test streaming
        logger.info("\nStreaming litellm call:")
        response_stream = await litellm.acompletion(
            model="ollama_chat/qwen2.5",
            messages=messages,
            tools=tools,
            base_url=base_url,
            temperature=0.1,
            max_tokens=100,
            stream=True,
        )

        complete_content = ""
        tool_calls_seen = False
        chunk_count = 0

        async for chunk in response_stream:
            chunk_count += 1
            if chunk.choices:
                delta = chunk.choices[0].delta

                logger.info(f"  Chunk {chunk_count}:")
                logger.info(f"    Content: '{getattr(delta, 'content', '')}'")
                logger.info(f"    Tool calls: {getattr(delta, 'tool_calls', None)}")

                if hasattr(delta, "content") and delta.content:
                    complete_content += delta.content

                if hasattr(delta, "tool_calls") and delta.tool_calls:
                    tool_calls_seen = True
                    logger.info(f"    Tool call details: {delta.tool_calls}")

        logger.info("\nStreaming summary:")
        logger.info(f"  Complete content: '{complete_content}'")
        logger.info(f"  Tool calls seen: {tool_calls_seen}")

        if not tool_calls_seen and "task_complete" in complete_content.lower():
            logger.warning("🚨 LITELLM ISSUE: Tool call in content, not in tool_calls!")

    except Exception as e:
        logger.error(f"litellm direct test failed: {e}")
        pytest.skip(f"Ollama not available: {e}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    pytest.main([__file__, "-v", "-s"])
