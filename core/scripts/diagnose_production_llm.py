#!/usr/bin/env python3
"""Diagnostic script to identify why production LLM returns malformed responses."""

import asyncio
import json
import logging
import os
import sys

# Add the core directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentarea_agents_sdk.models.llm_model import LLMModel, LLMRequest

logger = logging.getLogger(__name__)


async def test_production_llm_config(
    provider_type: str, model_name: str, endpoint_url: str = None, api_key: str = None
):
    """Test LLM configuration that matches production."""
    print("🧪 Testing LLM Configuration")
    print(f"Provider: {provider_type}")
    print(f"Model: {model_name}")
    print(f"Endpoint: {endpoint_url}")
    print(f"Has API Key: {bool(api_key)}")
    print("=" * 50)

    # Create LLM model
    llm_model = LLMModel(
        provider_type=provider_type,
        model_name=model_name,
        endpoint_url=endpoint_url,
        api_key=api_key,
    )

    # Test messages that match production
    messages = [
        {
            "role": "system",
            "content": "You are Test Agent, an AI agent that follows the ReAct (Reasoning + Acting) framework.\n\nComplete tasks efficiently\n\n## Current Task\nGoal: test\n\nSuccess Criteria:\n- Task completed successfully\n\n## Available Tools\n- task_complete: Mark task as completed\n- task_complete: Mark the task as completed when all success criteria are met\n\n## ReAct Framework Instructions\nYou MUST follow this exact pattern for EVERY action you take:\n\n1. **Thought**: First, analyze the current situation and what needs to be done\n2. **Observation**: Note what information you have and what you're missing  \n3. **Action**: Decide on the next action (tool call or response)\n4. **Result**: After a tool call, observe and interpret the results\n\nFor each step, explicitly state your reasoning process using these markers:\n\n**Thought:** [Your reasoning about the current situation]\n**Observation:** [What you observe from previous results or current context]\n**Action:** [What action you decide to take and why]\n\nAfter receiving tool results, always provide:\n**Result Analysis:** [Interpretation of the tool results and what they mean]\n\nExample flow:\n**Thought:** I need to search for information about X to complete the task.\n**Observation:** I don't have current information about X in my knowledge.\n**Action:** I'll use the web_search tool to find recent information.\n[Tool call happens]\n**Result Analysis:** The search returned Y, which shows that...\n**Thought:** Now that I have Y, I need to...\n\nCRITICAL RULES:\n- NEVER call tools without first showing your **Thought** and **Observation**\n- NEVER call task_complete without first demonstrating your work step-by-step\n- You must show your reasoning process for EVERY action, including the final completion\n- The task_complete tool requires detailed summary, reasoning, and result - prepare these thoughtfully\n\nContinue this pattern until the task is complete, then use the task_complete tool with comprehensive details.\n\nRemember: ALWAYS show your reasoning before taking actions. Users want to see your thought process.",
        },
        {"role": "user", "content": "test"},
    ]

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

    request = LLMRequest(
        messages=messages,
        tools=tools,
        temperature=None,  # Use model defaults
        max_tokens=None,  # Use model defaults
    )

    try:
        print("📡 Making streaming LLM call...")

        complete_content = ""
        complete_tool_calls = None
        final_usage = None
        final_cost = 0.0
        chunk_count = 0

        async for chunk in llm_model.ainvoke_stream(request):
            chunk_count += 1

            if chunk.content:
                complete_content += chunk.content
                print(
                    f"📝 Chunk {chunk_count}: '{chunk.content[:50]}{'...' if len(chunk.content) > 50 else ''}'"
                )

            if chunk.tool_calls:
                complete_tool_calls = chunk.tool_calls
                print(f"🔧 Tool calls in chunk {chunk_count}: {chunk.tool_calls}")

            if chunk.usage:
                final_usage = chunk.usage

            if chunk.cost:
                final_cost = chunk.cost

        print("\n" + "=" * 50)
        print("📊 FINAL RESULT:")
        print(f"Content: '{complete_content[:200]}{'...' if len(complete_content) > 200 else ''}'")
        print(f"Tool calls: {complete_tool_calls}")
        print(f"Cost: ${final_cost:.6f}")
        print(f"Total chunks: {chunk_count}")

        # Check for malformed response
        if not complete_tool_calls and complete_content:
            if "task_complete" in complete_content.lower():
                print("\n🚨 MALFORMED RESPONSE DETECTED!")
                print("Tool calls are None but content mentions task_complete")

                # Try to extract JSON from content
                try:
                    # Look for JSON patterns
                    import re

                    json_patterns = [
                        r'\{\s*"name"\s*:\s*"task_complete"[^}]*\}',
                        r'\{\s*"name"\s*:\s*"task_complete"[^}]*"arguments"[^}]*\}',
                    ]

                    for pattern in json_patterns:
                        matches = re.findall(pattern, complete_content, re.DOTALL)
                        if matches:
                            print(f"Found JSON pattern: {matches[0]}")
                            try:
                                parsed = json.loads(matches[0])
                                print(f"Parsed JSON: {parsed}")
                            except json.JSONDecodeError as e:
                                print(f"JSON parsing failed: {e}")
                            break

                except Exception as e:
                    print(f"Pattern extraction failed: {e}")
        else:
            print("\n✅ RESPONSE FORMAT IS CORRECT")
            if complete_tool_calls:
                print(f"Tool calls properly returned: {len(complete_tool_calls)} calls")

        return {
            "success": True,
            "content": complete_content,
            "tool_calls": complete_tool_calls,
            "cost": final_cost,
            "chunks": chunk_count,
            "malformed": not complete_tool_calls and "task_complete" in complete_content.lower(),
        }

    except Exception as e:
        print(f"\n❌ LLM call failed: {e}")
        print(f"Error type: {type(e).__name__}")
        return {"success": False, "error": str(e), "error_type": type(e).__name__}


async def main():
    """Main diagnostic function."""
    print("🔍 Production LLM Diagnostic Tool")
    print("=" * 50)

    # Test configurations
    test_configs = [
        {
            "name": "Local Ollama qwen2.5 (known working)",
            "provider_type": "ollama_chat",
            "model_name": "qwen2.5",
            "endpoint_url": f"http://{os.environ.get('LLM_DOCKER_HOST', 'localhost')}:11434",
            "api_key": None,
        },
        {
            "name": "OpenAI GPT-3.5 (if API key provided)",
            "provider_type": "openai",
            "model_name": "gpt-3.5-turbo",
            "endpoint_url": None,
            "api_key": os.environ.get("OPENAI_API_KEY"),
        },
        {
            "name": "Claude (if API key provided)",
            "provider_type": "anthropic",
            "model_name": "claude-3-haiku-20240307",
            "endpoint_url": None,
            "api_key": os.environ.get("ANTHROPIC_API_KEY"),
        },
    ]

    # Allow custom configuration via command line
    if len(sys.argv) >= 3:
        custom_config = {
            "name": "Custom Configuration",
            "provider_type": sys.argv[1],
            "model_name": sys.argv[2],
            "endpoint_url": sys.argv[3] if len(sys.argv) > 3 else None,
            "api_key": sys.argv[4] if len(sys.argv) > 4 else None,
        }
        test_configs = [custom_config]
        print(f"Using custom configuration: {sys.argv[1]}/{sys.argv[2]}")

    results = []

    for config in test_configs:
        if config["provider_type"] in ["openai", "anthropic"] and not config["api_key"]:
            print(f"\n⏭️ Skipping {config['name']} - no API key provided")
            continue

        print(f"\n🧪 Testing: {config['name']}")
        print("-" * 30)

        result = await test_production_llm_config(
            provider_type=config["provider_type"],
            model_name=config["model_name"],
            endpoint_url=config["endpoint_url"],
            api_key=config["api_key"],
        )

        result["config"] = config
        results.append(result)

        # Wait a bit between tests
        await asyncio.sleep(1)

    # Summary
    print("\n" + "=" * 50)
    print("📋 SUMMARY")
    print("=" * 50)

    working_configs = []
    malformed_configs = []
    failed_configs = []

    for result in results:
        config_name = result["config"]["name"]
        if not result["success"]:
            failed_configs.append(config_name)
            print(f"❌ {config_name}: FAILED - {result.get('error', 'Unknown error')}")
        elif result.get("malformed"):
            malformed_configs.append(config_name)
            print(f"🚨 {config_name}: MALFORMED RESPONSES")
        else:
            working_configs.append(config_name)
            print(f"✅ {config_name}: WORKING CORRECTLY")

    print(
        f"\n📊 Results: {len(working_configs)} working, {len(malformed_configs)} malformed, {len(failed_configs)} failed"
    )

    if malformed_configs:
        print(f"\n🎯 MALFORMED RESPONSE SOURCES: {', '.join(malformed_configs)}")
        print("These configurations produce the same malformed responses as your production!")

    if working_configs:
        print(f"\n✅ WORKING CONFIGURATIONS: {', '.join(working_configs)}")
        print("These configurations work correctly and should be used instead.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    if len(sys.argv) > 1 and sys.argv[1] in ["-h", "--help"]:
        print("Usage:")
        print(
            "  python diagnose_production_llm.py                                    # Test all known configurations"
        )
        print(
            "  python diagnose_production_llm.py <provider> <model> [endpoint] [key] # Test custom configuration"
        )
        print("")
        print("Examples:")
        print("  python diagnose_production_llm.py                                    # Test all")
        print("  python diagnose_production_llm.py ollama_chat qwen2.5 http://localhost:11434")
        print("  python diagnose_production_llm.py openai gpt-3.5-turbo '' sk-...")
        sys.exit(0)

    asyncio.run(main())
