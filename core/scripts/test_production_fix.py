#!/usr/bin/env python3
"""Test script to verify the fix works with exact production data."""

import os
import sys

# Add the core directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentarea_execution.workflows.helpers import ToolCallExtractor


def test_production_data():
    """Test with the exact production data provided."""
    print("🧪 Testing Production Data Fix")
    print("=" * 50)

    # First call from production
    message1 = {
        "content": '{\n  "name": "task_complete",\n  "arguments": {}\n}',
        "cost": 0,
        "role": "assistant",
        "tool_calls": None,  # This is the bug!
        "usage": {"completion_tokens": 0, "prompt_tokens": 0, "total_tokens": 0},
    }

    print("📥 First Production Message:")
    print(f"  Content: {message1['content']}")
    print(f"  Tool Calls: {message1['tool_calls']}")

    tool_calls1 = ToolCallExtractor.extract_tool_calls(message1)
    print(f"✅ Extracted {len(tool_calls1)} tool calls")
    if tool_calls1:
        print(f"  Tool: {tool_calls1[0].function['name']}")
        print(f"  Arguments: {tool_calls1[0].function['arguments']}")

    print()

    # Second call from production
    message2 = {
        "content": '{"name": "task_complete", "arguments": {"result": "Since no specific task was provided and the goal \'test\' is vague, I\'ve completed this iteration with a basic task completion message as instructed."}}',
        "cost": 0,
        "role": "assistant",
        "tool_calls": None,  # Still the bug!
        "usage": {"completion_tokens": 0, "prompt_tokens": 0, "total_tokens": 0},
    }

    print("📥 Second Production Message:")
    print(f"  Content: {message2['content'][:100]}...")
    print(f"  Tool Calls: {message2['tool_calls']}")

    tool_calls2 = ToolCallExtractor.extract_tool_calls(message2)
    print(f"✅ Extracted {len(tool_calls2)} tool calls")
    if tool_calls2:
        print(f"  Tool: {tool_calls2[0].function['name']}")
        print(f"  Arguments: {tool_calls2[0].function['arguments'][:100]}...")

    print()

    # Verify the fix works
    success = True
    if len(tool_calls1) != 1 or tool_calls1[0].function["name"] != "task_complete":
        print("❌ First message parsing failed")
        success = False

    if len(tool_calls2) != 1 or tool_calls2[0].function["name"] != "task_complete":
        print("❌ Second message parsing failed")
        success = False

    if success:
        print("🎉 SUCCESS: Production data is now correctly parsed!")
        print("   Workflows should now complete properly when LLM returns malformed responses.")
    else:
        print("💥 FAILURE: Production data parsing still has issues")

    return success


if __name__ == "__main__":
    success = test_production_data()
    sys.exit(0 if success else 1)
