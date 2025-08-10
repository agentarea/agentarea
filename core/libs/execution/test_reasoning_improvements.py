#!/usr/bin/env python3
"""Test script to demonstrate the reasoning improvements.

This shows how the enhanced completion tool and prompts encourage better reasoning.
"""

import sys

sys.path.append('core/libs/execution')

from agentarea_agents_sdk.prompts import PromptBuilder
from agentarea_agents_sdk.tools.completion_tool import CompletionTool


def test_completion_tool_improvements():
    """Test the improved completion tool."""
    print("=== Testing Improved Completion Tool ===\n")

    tool = CompletionTool()

    print(f"Tool Name: {tool.name}")
    print(f"Tool Description: {tool.description}")
    print("\nTool Schema:")
    schema = tool.get_schema()

    print("Required Parameters:")
    for param, details in schema["parameters"]["properties"].items():
        required = "✅ REQUIRED" if param in schema["parameters"]["required"] else "⚪ Optional"
        print(f"  - {param}: {details['description']} ({required})")

    print("\n" + "="*60)
    print("COMPARISON: Old vs New")
    print("="*60)
    print("OLD:")
    print("  - Description: 'Call when task is done'")
    print("  - Required: ['result']")
    print("  - Encourages: Quick completion without reasoning")
    print("\nNEW:")
    print("  - Description: 'Mark task as completed ONLY after showing reasoning...'")
    print("  - Required: ['summary', 'reasoning', 'result']")
    print("  - Encourages: Detailed reasoning and comprehensive completion")


async def test_completion_tool_execution():
    """Test the completion tool execution."""
    print("\n=== Testing Completion Tool Execution ===\n")

    tool = CompletionTool()

    # Test with proper parameters
    result = await tool.execute(
        summary="Successfully wrote a poem about nature with vivid imagery and metaphors",
        reasoning="The task asked for a poem, and I created one that meets the success criteria by including creative language, proper structure, and engaging content",
        result="A beautiful poem about nature:\n\nWhispers of the ancient trees,\nDancing in the morning breeze..."
    )

    print("✅ Completion Tool Result:")
    print(f"  - Success: {result['success']}")
    print(f"  - Completed: {result['completed']}")
    print(f"  - Summary: {result['summary'][:50]}...")
    print(f"  - Reasoning: {result['reasoning'][:50]}...")
    print(f"  - Final Result: {result['final_result'][:50]}...")

    print("\nFull Result Preview:")
    print("-" * 40)
    print(result['result'][:200] + "...")


def test_react_prompt_improvements():
    """Test the improved ReAct prompts."""
    print("\n=== Testing Improved ReAct Prompts ===\n")

    # Create a sample prompt
    prompt = PromptBuilder.build_react_system_prompt(
        agent_name="PoetryAgent",
        agent_instruction="You are a creative writing assistant specialized in poetry.",
        goal_description="Write a poem about nature",
        success_criteria=["Create original poem", "Use vivid imagery", "Include metaphors"],
        available_tools=[
            {"name": "research_topic", "description": "Research information about a topic"},
            {"name": "task_complete", "description": "Mark task as completed ONLY after showing your reasoning and ensuring all success criteria are met. Must include detailed summary of work done."}
        ]
    )

    # Check for key improvements
    improvements = [
        ("Explicit reasoning requirement", "NEVER call tools without first showing your **Thought**"),
        ("Completion prevention", "NEVER call task_complete without first demonstrating"),
        ("Step-by-step requirement", "must show your reasoning process for EVERY action"),
        ("Detailed completion", "task_complete tool requires detailed summary, reasoning"),
        ("Critical rules section", "CRITICAL RULES:")
    ]

    print("Checking for reasoning improvements in prompt:")
    for description, marker in improvements:
        present = marker in prompt
        status = "✅" if present else "❌"
        print(f"{status} {description}")

    print(f"\nPrompt length: {len(prompt)} characters")
    print("This encourages agents to show their work before taking actions!")


def demonstrate_expected_behavior():
    """Demonstrate the expected agent behavior."""
    print("\n=== Expected Agent Behavior ===\n")

    print("BEFORE (problematic):")
    print("Agent: [immediately calls task_complete with minimal result]")
    print("Result: User sees no reasoning, just final answer")

    print("\nAFTER (improved):")
    print("Agent: **Thought:** I need to write a poem about nature...")
    print("Agent: **Observation:** The task requires original content with vivid imagery...")
    print("Agent: **Action:** I'll create a poem that incorporates natural elements...")
    print("Agent: [writes the poem]")
    print("Agent: **Thought:** Now I should complete the task with proper documentation...")
    print("Agent: [calls task_complete with summary, reasoning, and result]")
    print("Result: User sees the complete thought process and detailed completion")


def main():
    """Run all tests."""
    print("Testing Agent Reasoning Improvements\n")

    test_completion_tool_improvements()

    import asyncio
    asyncio.run(test_completion_tool_execution())

    test_react_prompt_improvements()
    demonstrate_expected_behavior()

    print("\n" + "="*60)
    print("SUMMARY OF IMPROVEMENTS")
    print("="*60)
    print("✅ Enhanced completion tool with detailed requirements")
    print("✅ Improved ReAct prompts with explicit reasoning rules")
    print("✅ Prevention of premature task completion")
    print("✅ Encouragement of step-by-step thinking")
    print("✅ Better user experience with visible reasoning")

    print("\nThese changes should prevent agents from immediately calling")
    print("task_complete and instead encourage them to show their work!")


if __name__ == "__main__":
    main()
