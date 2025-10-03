#!/usr/bin/env python3
"""
Test for ReAct framework behavior issues.

This test specifically addresses the issue where agents immediately call
task_complete without showing their reasoning process first.
"""

import asyncio
import logging

import pytest

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_react_framework_natural_response():
    """Test that LLM provides natural responses before tool calls in ReAct framework."""
    try:
        from agentarea_agents_sdk.models.llm_model import LLMModel, LLMRequest
    except ImportError:
        pytest.skip("LLM model not available")

    # Test with different tool_choice settings
    llm_model = LLMModel(
        provider_type="ollama_chat",
        model_name="qwen2.5",
        api_key=None,
        endpoint_url="localhost:11434",
    )

    # ReAct framework system prompt
    system_prompt = """You are a helpful AI assistant that follows the ReAct framework.

When given a task, you should:
1. First provide your reasoning and thinking process
2. Explain what you're going to do
3. Only then call tools if needed

For this task: Tell me a short programming joke and explain why it's funny.

IMPORTANT: 
- First respond with your reasoning and the actual joke
- Only call task_complete AFTER you've provided the joke and explanation
- Do not call tools immediately without providing content first"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "Tell me a short joke about programming"},
    ]

    tools = [
        {
            "type": "function",
            "function": {
                "name": "task_complete",
                "description": "Mark task as completed",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "summary": {
                            "type": "string",
                            "description": "Summary of what was accomplished",
                        }
                    },
                    "required": [],
                },
            },
        }
    ]

    # Test different configurations
    test_configs = [
        {"tools": None, "name": "No Tools"},
        {"tools": tools, "name": "With Tools - Auto Choice"},
    ]

    results = {}

    for config in test_configs:
        logger.info(f"\n🧪 Testing: {config['name']}")

        request = LLMRequest(
            messages=messages, tools=config["tools"], temperature=0.7, max_tokens=500
        )

        response = await llm_model.complete(request)

        logger.info(f"📝 Content length: {len(response.content)} chars")
        logger.info(f"🔧 Tool calls: {len(response.tool_calls) if response.tool_calls else 0}")
        logger.info(f"📄 Content preview: {response.content[:100]!r}")

        # Analyze response behavior
        has_content = len(response.content) > 10
        has_tool_calls = response.tool_calls and len(response.tool_calls) > 0
        content_has_joke = any(
            word in response.content.lower() for word in ["joke", "funny", "programming"]
        )

        behavior = {
            "has_meaningful_content": has_content,
            "has_tool_calls": has_tool_calls,
            "content_contains_joke": content_has_joke,
            "immediate_tool_call": has_tool_calls and not has_content,
            "proper_flow": has_content and content_has_joke,
        }

        results[config["name"]] = {"response": response, "behavior": behavior}

        logger.info(f"📊 Behavior analysis: {behavior}")

    # Assertions and analysis
    no_tools_result = results["No Tools"]
    with_tools_result = results["With Tools - Auto Choice"]

    # Without tools, should always provide content
    assert no_tools_result["behavior"]["has_meaningful_content"], (
        "Should provide content when no tools available"
    )
    assert no_tools_result["behavior"]["proper_flow"], (
        "Should provide joke when no tools forcing behavior"
    )

    # With tools, check if it's following proper ReAct flow
    if with_tools_result["behavior"]["immediate_tool_call"]:
        logger.warning(
            "⚠️ IDENTIFIED ISSUE: LLM is immediately calling tools without providing reasoning!"
        )
        logger.warning("This suggests the model or tool configuration is forcing tool usage")

        # This is the problematic behavior we want to document
        assert False, (
            "ReAct framework issue detected: LLM calls tools immediately without reasoning. "
            "This may be due to tool_choice configuration or model behavior."
        )

    elif with_tools_result["behavior"]["proper_flow"]:
        logger.info("✅ LLM is following proper ReAct flow")
        assert True

    else:
        logger.info("ℹ️ LLM provided response but didn't follow expected ReAct pattern")
        # This might be acceptable depending on the specific prompt
        assert with_tools_result["behavior"]["has_meaningful_content"], (
            "Should at least provide some content"
        )

    return results


@pytest.mark.integration
@pytest.mark.asyncio
async def test_tool_choice_configurations():
    """Test how different tool_choice settings affect LLM behavior."""
    try:
        import litellm
    except ImportError:
        pytest.skip("LiteLLM not available")

    messages = [
        {
            "role": "system",
            "content": "You are a helpful assistant. Provide natural responses and only call tools when appropriate.",
        },
        {"role": "user", "content": "Tell me a programming joke"},
    ]

    tools = [
        {
            "type": "function",
            "function": {
                "name": "task_complete",
                "description": "Complete the task",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        }
    ]

    # Test different tool_choice configurations
    configurations = [
        {"tool_choice": "auto", "name": "Auto Choice"},
        {"tool_choice": "none", "name": "No Tools Forced"},
        # Note: "required" would force tool usage, which is problematic for ReAct
    ]

    results = {}

    for config in configurations:
        logger.info(f"\n🧪 Testing tool_choice: {config['name']}")

        try:
            response = await litellm.acompletion(
                model="ollama_chat/qwen2.5",
                messages=messages,
                tools=tools,
                tool_choice=config["tool_choice"],
                base_url="http://localhost:11434",
                temperature=0.7,
            )

            message = response.choices[0].message
            content = message.content or ""
            tool_calls = getattr(message, "tool_calls", None) or []

            behavior = {
                "content_length": len(content),
                "has_content": len(content) > 10,
                "tool_calls_count": len(tool_calls),
                "immediate_tool_use": len(tool_calls) > 0 and len(content) < 10,
            }

            results[config["name"]] = behavior

            logger.info(f"📄 Content: {content[:50]!r}")
            logger.info(f"🔧 Tool calls: {len(tool_calls)}")
            logger.info(f"📊 Immediate tool use: {behavior['immediate_tool_use']}")

        except Exception as e:
            logger.error(f"❌ Configuration {config['name']} failed: {e}")
            results[config["name"]] = {"error": str(e)}

    # Analysis
    logger.info("\n📊 Tool Choice Analysis:")
    for name, result in results.items():
        if "error" not in result:
            logger.info(
                f"  {name}: Content={result['has_content']}, Tools={result['tool_calls_count']}, Immediate={result['immediate_tool_use']}"
            )
        else:
            logger.info(f"  {name}: ERROR - {result['error']}")

    # Identify the best configuration for ReAct framework
    best_config = None
    for name, result in results.items():
        if "error" not in result and result["has_content"] and not result["immediate_tool_use"]:
            best_config = name
            break

    if best_config:
        logger.info(f"✅ Best configuration for ReAct: {best_config}")
    else:
        logger.warning("⚠️ No configuration provided proper ReAct behavior")

    return results


if __name__ == "__main__":
    """Run ReAct framework behavior tests directly."""

    async def main():
        logger.info("🧪 Testing ReAct Framework Behavior")
        logger.info("=" * 50)

        try:
            # Test 1: ReAct framework natural response
            logger.info("Test 1: ReAct Framework Natural Response")
            await test_react_framework_natural_response()
            logger.info("✅ ReAct test completed")

            # Test 2: Tool choice configurations
            logger.info("\nTest 2: Tool Choice Configurations")
            await test_tool_choice_configurations()
            logger.info("✅ Tool choice test completed")

            logger.info("\n🎉 All ReAct framework tests completed!")

        except AssertionError as e:
            logger.error(f"❌ Test assertion failed: {e}")
            logger.error("This indicates a ReAct framework configuration issue")
        except Exception as e:
            logger.error(f"❌ Test failed with error: {e}")
            import traceback

            traceback.print_exc()

    asyncio.run(main())
