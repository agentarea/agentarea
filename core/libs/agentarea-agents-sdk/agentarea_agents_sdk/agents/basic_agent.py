#!/usr/bin/env python3
"""Basic agent runner using AgentArea Agents SDK.

Run examples:

  - Streaming (default):
      python -m agentarea_agents_sdk.basic_agent "Calculate 25 * 4 + 15 and explain"

  - Non-streaming:
      python -m agentarea_agents_sdk.basic_agent "What is 7 * 8?" --no-stream

  - Custom model/name/instruction/goal:
      python -m agentarea_agents_sdk.basic_agent "Help me understand factorials" \
        --model ollama_chat/qwen2.5 \
        --name "Tutor" \
        --instruction "You are a patient math tutor." \
        --goal "Explain what 5! equals and why"
"""

import argparse
import asyncio
import logging
import sys

from agentarea_agents_sdk.tools.example_decorator_tool import MathToolset
from agentarea_agents_sdk.tools.file_toolset import FileToolset

from .agent import Agent

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a basic AgentArea agent")
    parser.add_argument(
        "task",
        type=str,
        nargs="?",
        default="Say hello",
        help="Task or question for the agent",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="ollama_chat/qwen2.5",
        help="Model in provider/model format (e.g., ollama_chat/qwen2.5, openai/gpt-4o)",
    )
    parser.add_argument(
        "--name",
        type=str,
        default="Basic Agent",
        help="Agent name used in prompts",
    )
    parser.add_argument(
        "--instruction",
        type=str,
        default="You are a helpful assistant.",
        help="Agent instruction/role",
    )
    parser.add_argument(
        "--goal",
        type=str,
        default=None,
        help="Optional goal description (defaults to task)",
    )
    parser.add_argument(
        "--no-stream",
        action="store_true",
        help="Disable streaming and return a single complete response",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.3,
        help="LLM temperature (0.0-1.0)",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=500,
        help="Maximum tokens per response",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=10,
        help="Maximum reasoning/acting iterations",
    )
    return parser.parse_args()


async def run_agent(
    task: str,
    *,
    model: str,
    name: str,
    instruction: str,
    goal: str | None,
    stream: bool,
    temperature: float,
    max_tokens: int,
    max_iterations: int,
) -> None:
    if "/" not in model:
        raise ValueError(
            "--model must be in format 'provider/model_name', e.g., 'ollama_chat/qwen2.5'"
        )
    model_provider, model_name = model.split("/", 1)

    agent = Agent(
        name=name,
        instruction=instruction,
        model_provider=model_provider,
        model_name=model_name,
        temperature=temperature,
        max_tokens=max_tokens,
        max_iterations=max_iterations,
        tools=[MathToolset(), FileToolset()],
    )

    logger.info("Agent: %s | Model: %s", name, model)
    logger.info("Task: %s", task)
    if goal:
        logger.info("Goal: %s", goal)
    logger.info("%s", "-" * 40)

    if stream:
        async for content in agent.run_stream(task, goal=goal):
            sys.stdout.write(content)
            sys.stdout.flush()
        sys.stdout.write("\n")
    else:
        result = await agent.run(task, goal=goal)
        logger.info("%s", result)


def main() -> None:
    args = parse_args()
    asyncio.run(
        run_agent(
            args.task,
            model=args.model,
            name=args.name,
            instruction=args.instruction,
            goal=args.goal,
            stream=not args.no_stream,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
            max_iterations=args.max_iterations,
        )
    )


if __name__ == "__main__":
    main()
