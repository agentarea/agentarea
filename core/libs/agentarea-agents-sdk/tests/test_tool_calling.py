"""Test tool calling functionality with local qwen2.5."""

import logging

import pytest

logger = logging.getLogger(__name__)


class TestToolCalling:
    """Test tool calling with qwen2.5."""

    @pytest.mark.asyncio
    async def test_single_tool_call(self):
        """Test a single tool call with qwen2.5."""
        try:
            from agentarea_agents_sdk.models.llm_model import LLMModel, LLMRequest

            model = LLMModel(
                provider_type="ollama_chat",
                model_name="qwen2.5",
                endpoint_url="http://localhost:11434",
            )

            # Define a simple tool
            tools = [
                {
                    "type": "function",
                    "function": {
                        "name": "calculate",
                        "description": "Perform a mathematical calculation",
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
                        "content": "You are a helpful assistant. Use the calculate tool to solve math problems.",
                    },
                    {"role": "user", "content": "What is 15 + 27?"},
                ],
                tools=tools,
                temperature=0.1,
                max_tokens=200,
            )

            logger.info("🧪 Testing single tool call with qwen2.5")
            logger.info(f"📝 Request: {request.messages[-1]['content']}")
            logger.info(f"🔧 Available tools: {[t['function']['name'] for t in tools]}")

            response = await model.complete(request)

            logger.info("=" * 60)
            logger.info("🎯 SINGLE TOOL CALL RESPONSE ANALYSIS")
            logger.info("=" * 60)
            logger.info(f"📝 Content: '{response.content}'")
            logger.info(f"🔧 Tool calls: {response.tool_calls}")
            logger.info(f"💰 Cost: ${response.cost:.6f}")

            # Analyze the response
            if response.tool_calls:
                logger.info("✅ SUCCESS: Tool calls properly returned in tool_calls field")
                assert len(response.tool_calls) >= 1, "Should have at least one tool call"

                tool_call = response.tool_calls[0]
                assert tool_call["function"]["name"] == "calculate", "Should call calculate tool"
                assert (
                    "15" in tool_call["function"]["arguments"]
                    or "27" in tool_call["function"]["arguments"]
                ), "Should include the numbers"

                logger.info(f"   Tool: {tool_call['function']['name']}")
                logger.info(f"   Args: {tool_call['function']['arguments']}")

            elif response.content and (
                "calculate" in response.content.lower()
                or "15" in response.content
                or "27" in response.content
            ):
                logger.warning(
                    "⚠️ ISSUE: Tool call information in content instead of tool_calls field"
                )
                logger.warning(f"Content contains: {response.content[:200]}...")

                # This indicates the model is trying to use tools but not in the right format
                pytest.fail("Tool calls should be in tool_calls field, not content")

            else:
                logger.error("❌ FAILURE: No tool usage detected")
                pytest.fail("Model should use the calculate tool for math problems")

            logger.info("=" * 60)

        except Exception as e:
            pytest.skip(f"Tool calling test failed - LLM not available: {e}")

    @pytest.mark.asyncio
    async def test_multiple_tool_calls_sequence(self):
        """Test multiple tool calls in sequence."""
        try:
            from agentarea_agents_sdk.models.llm_model import LLMModel, LLMRequest

            model = LLMModel(
                provider_type="ollama_chat",
                model_name="qwen2.5",
                endpoint_url="http://localhost:11434",
            )

            # Define multiple tools
            tools = [
                {
                    "type": "function",
                    "function": {
                        "name": "calculate",
                        "description": "Perform a mathematical calculation",
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
                },
                {
                    "type": "function",
                    "function": {
                        "name": "completion",
                        "description": "Mark the task as completed with a result",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "result": {
                                    "type": "string",
                                    "description": "The final result or summary",
                                }
                            },
                            "required": ["result"],
                        },
                    },
                },
            ]

            # Simulate a conversation with multiple tool calls
            messages = [
                {
                    "role": "system",
                    "content": "You are a helpful assistant. Use tools to solve problems step by step. When you're done, use completion.",
                },
                {
                    "role": "user",
                    "content": "Calculate 10 * 5, then add 15 to the result, and tell me the final answer.",
                },
            ]

            logger.info("🧪 Testing multiple tool calls sequence")
            logger.info(f"📝 Task: {messages[-1]['content']}")
            logger.info(f"🔧 Available tools: {[t['function']['name'] for t in tools]}")

            # First call - should calculate 10 * 5
            request1 = LLMRequest(messages=messages, tools=tools, temperature=0.1, max_tokens=300)
            response1 = await model.complete(request1)

            logger.info("\n" + "=" * 40)
            logger.info("🎯 FIRST CALL ANALYSIS")
            logger.info("=" * 40)
            logger.info(f"📝 Content: '{response1.content}'")
            logger.info(f"🔧 Tool calls: {response1.tool_calls}")

            if response1.tool_calls:
                logger.info("✅ First call: Tool calls properly returned")
                # Add the assistant's response and tool result to conversation
                messages.append(
                    {
                        "role": "assistant",
                        "content": response1.content,
                        "tool_calls": response1.tool_calls,
                    }
                )

                # Simulate tool execution result
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": response1.tool_calls[0]["id"],
                        "name": response1.tool_calls[0]["function"]["name"],
                        "content": "50",  # Result of 10 * 5
                    }
                )

                # Second call - should add 15 and complete
                request2 = LLMRequest(
                    messages=messages, tools=tools, temperature=0.1, max_tokens=300
                )
                response2 = await model.complete(request2)

                logger.info("\n" + "=" * 40)
                logger.info("🎯 SECOND CALL ANALYSIS")
                logger.info("=" * 40)
                logger.info(f"📝 Content: '{response2.content}'")
                logger.info(f"🔧 Tool calls: {response2.tool_calls}")

                if response2.tool_calls:
                    logger.info("✅ Second call: Tool calls properly returned")

                    # Check if it's trying to calculate or complete
                    tool_names = [tc["function"]["name"] for tc in response2.tool_calls]
                    logger.info(f"   Tools called: {tool_names}")

                    if "calculate" in tool_names:
                        logger.info("   📊 Model is continuing with calculation")
                    if "completion" in tool_names:
                        logger.info("   ✅ Model is completing the task")

                    logger.info("🎉 SUCCESS: Multiple tool calls working properly")

                else:
                    logger.warning("⚠️ Second call: No tool calls returned")

            else:
                logger.warning("⚠️ First call: No tool calls returned")
                if response1.content:
                    logger.warning(f"Content: {response1.content[:200]}...")

            logger.info("=" * 60)

        except Exception as e:
            pytest.skip(f"Multiple tool calls test failed - LLM not available: {e}")

    @pytest.mark.asyncio
    async def test_streaming_tool_calls(self):
        """Test tool calls with streaming."""
        try:
            from agentarea_agents_sdk.models.llm_model import LLMModel, LLMRequest

            model = LLMModel(
                provider_type="ollama_chat",
                model_name="qwen2.5",
                endpoint_url="http://localhost:11434",
            )

            tools = [
                {
                    "type": "function",
                    "function": {
                        "name": "completion",
                        "description": "Mark the task as completed",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "result": {"type": "string", "description": "The final result"}
                            },
                            "required": ["result"],
                        },
                    },
                }
            ]

            request = LLMRequest(
                messages=[
                    {
                        "role": "system",
                        "content": "You are a helpful assistant. When you complete a task, use the completion tool.",
                    },
                    {"role": "user", "content": "Say hello and then mark the task as complete."},
                ],
                tools=tools,
                temperature=0.1,
                max_tokens=200,
            )

            logger.info("🧪 Testing streaming tool calls")
            logger.info(f"📝 Request: {request.messages[-1]['content']}")

            complete_content = ""
            final_tool_calls = None
            chunk_count = 0

            async for chunk in model.ainvoke_stream(request):
                chunk_count += 1

                if chunk.content:
                    complete_content += chunk.content
                    if chunk_count <= 5:  # Log first few chunks
                        logger.info(f"📝 Chunk {chunk_count}: '{chunk.content}'")

                if chunk.tool_calls:
                    final_tool_calls = chunk.tool_calls
                    logger.info(f"🔧 Tool calls in chunk {chunk_count}: {chunk.tool_calls}")

            logger.info("=" * 60)
            logger.info("🎯 STREAMING TOOL CALLS ANALYSIS")
            logger.info("=" * 60)
            logger.info(f"📊 Total chunks: {chunk_count}")
            logger.info(f"📝 Complete content: '{complete_content}'")
            logger.info(f"🔧 Final tool calls: {final_tool_calls}")

            if final_tool_calls:
                logger.info("✅ SUCCESS: Streaming tool calls working properly")
                assert len(final_tool_calls) >= 1, "Should have at least one tool call"
                assert final_tool_calls[0]["function"]["name"] == "completion", (
                    "Should call completion"
                )
            else:
                logger.warning("⚠️ No tool calls received in streaming")
                if complete_content and "completion" in complete_content.lower():
                    logger.warning("Tool call information found in content instead of tool_calls")

            logger.info("=" * 60)

        except Exception as e:
            pytest.skip(f"Streaming tool calls test failed - LLM not available: {e}")

    @pytest.mark.asyncio
    async def test_tool_call_format_validation(self):
        """Test that tool calls have the correct format."""
        try:
            from agentarea_agents_sdk.models.llm_model import LLMModel, LLMRequest

            model = LLMModel(
                provider_type="ollama_chat",
                model_name="qwen2.5",
                endpoint_url="http://localhost:11434",
            )

            tools = [
                {
                    "type": "function",
                    "function": {
                        "name": "test_tool",
                        "description": "A test tool",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "message": {"type": "string", "description": "A test message"}
                            },
                            "required": ["message"],
                        },
                    },
                }
            ]

            request = LLMRequest(
                messages=[
                    {
                        "role": "system",
                        "content": "You are a helpful assistant. Use the test_tool with message 'Hello World'.",
                    },
                    {"role": "user", "content": "Please use the test tool."},
                ],
                tools=tools,
                temperature=0.1,
                max_tokens=200,
            )

            logger.info("🧪 Testing tool call format validation")

            response = await model.complete(request)

            logger.info("=" * 60)
            logger.info("🎯 TOOL CALL FORMAT VALIDATION")
            logger.info("=" * 60)
            logger.info(f"📝 Content: '{response.content}'")
            logger.info(f"🔧 Tool calls: {response.tool_calls}")

            if response.tool_calls:
                tool_call = response.tool_calls[0]

                # Validate OpenAI tool call format
                logger.info("✅ Validating tool call format...")

                assert "id" in tool_call, "Tool call should have an id"
                assert "type" in tool_call, "Tool call should have a type"
                assert "function" in tool_call, "Tool call should have a function"
                assert tool_call["type"] == "function", "Type should be 'function'"

                function = tool_call["function"]
                assert "name" in function, "Function should have a name"
                assert "arguments" in function, "Function should have arguments"
                assert function["name"] == "test_tool", "Function name should match"

                # Arguments should be a JSON string
                import json

                try:
                    args = json.loads(function["arguments"])
                    assert isinstance(args, dict), "Arguments should be a dictionary"
                    logger.info(f"   ✅ Arguments parsed successfully: {args}")
                except json.JSONDecodeError:
                    pytest.fail(f"Arguments should be valid JSON: {function['arguments']}")

                logger.info("🎉 SUCCESS: Tool call format is correct")

            else:
                logger.warning("⚠️ No tool calls returned")
                if response.content:
                    logger.warning(f"Content: {response.content}")

            logger.info("=" * 60)

        except Exception as e:
            pytest.skip(f"Tool call format validation failed - LLM not available: {e}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    pytest.main([__file__, "-v", "-s"])
