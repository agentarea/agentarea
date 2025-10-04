#!/usr/bin/env python3
"""Simple example demonstrating the Agent class usage."""

import asyncio
import os
import sys

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent import create_agent


async def streaming_math_example():
    """Streaming math calculation example."""
    print("🧮 Streaming Math Example")
    print("=" * 50)

    # Create a math assistant agent
    agent = create_agent(
        name="Math Assistant",
        instruction="You are a helpful math assistant that solves problems step by step.",
        model="ollama_chat/qwen2.5",
    )

    # Run a simple calculation with streaming
    task = "Calculate 25 * 4 + 15 and explain your work"

    print(f"Task: {task}\n")
    print("Agent Response (Streaming):")
    print("-" * 30)

    async for content in agent.run_stream(task):
        print(content, end="", flush=True)

    print("\n" + "=" * 50)


async def non_streaming_example():
    """Non-streaming example."""
    print("\n⚡ Non-Streaming Example")
    print("=" * 50)

    agent = create_agent(
        name="Quick Assistant",
        instruction="You are a quick assistant that provides concise answers.",
        model="ollama_chat/qwen2.5",
    )

    # Use the run method for complete response
    result = await agent.run("What is 7 * 8?")

    print("Task: What is 7 * 8?")
    print("Agent Response (Complete):")
    print("-" * 30)
    print(result)
    print("=" * 50)


async def reasoning_example():
    """Example with more complex reasoning using streaming."""
    print("\n🤔 Reasoning Example (Streaming)")
    print("=" * 50)

    # Create a reasoning agent
    agent = create_agent(
        name="Logic Assistant",
        instruction="You are a logical reasoning assistant that thinks through problems carefully.",
        model="ollama_chat/qwen2.5",
    )

    task = "If I have 12 apples and I give away 1/3 of them, then buy 8 more apples, how many apples do I have in total?"

    print(f"Task: {task}\n")
    print("Agent Response:")
    print("-" * 30)

    async for content in agent.run_stream(task):
        print(content, end="", flush=True)

    print("\n" + "=" * 50)


async def custom_agent_example():
    """Example with custom agent configuration."""
    print("\n⚙️ Custom Agent Configuration Example")
    print("=" * 50)

    from agent import Agent

    # Create agent with custom parameters
    agent = Agent(
        name="Custom Assistant",
        instruction="You are a precise assistant that provides detailed explanations.",
        model_provider="ollama_chat",
        model_name="qwen2.5",
        temperature=0.1,  # Lower temperature for more deterministic responses
        max_tokens=200,  # Shorter responses
        max_iterations=3,  # Fewer iterations
        include_default_tools=True,
    )

    task = "Explain what 5 factorial equals"

    print(f"Task: {task}")
    print("Custom Agent Response:")
    print("-" * 30)

    result = await agent.run(task)
    print(result)
    print("=" * 50)


async def main():
    """Run all examples."""
    print("🚀 AgentArea Agents SDK - Usage Examples\n")

    try:
        await streaming_math_example()
        await non_streaming_example()
        await reasoning_example()
        await custom_agent_example()

        print("\n🎉 All examples completed successfully!")

    except Exception as e:
        print(f"\n❌ Example failed: {e}")
        print("Make sure you have Ollama running with qwen2.5 model available.")


if __name__ == "__main__":
    asyncio.run(main())
