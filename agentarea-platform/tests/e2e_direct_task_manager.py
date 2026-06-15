#!/usr/bin/env python3
"""E2E test: DirectTaskManager — agent execution without Temporal.

Proves the BaseTaskManager abstraction works with a non-Temporal implementation.
Same interface, same skill disclosure, but runs entirely in-process.

No Docker, no Temporal, no workers, no K8s. Just Python.

Usage:
    cd agentarea-platform
    uv run python tests/e2e_direct_task_manager.py
"""

import asyncio
import os
import sys
from uuid import uuid4

from dotenv import load_dotenv

_script_dir = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(_script_dir, "..", "..", ".env.local"))

from agentarea_tasks.direct_task_manager import DirectTaskManager
from agentarea_tasks.domain.models import AgentTask

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
if not OPENROUTER_API_KEY:
    print("ERROR: OPENROUTER_API_KEY not set")
    sys.exit(1)


async def main():
    print("=" * 60)
    print("E2E: DirectTaskManager (no Temporal)")
    print("=" * 60)

    # Create manager — no DB, no Temporal, just LLM config
    manager = DirectTaskManager(
        provider_type="openrouter",
        model_name="meta-llama/llama-3.3-70b-instruct",
        api_key=OPENROUTER_API_KEY,
        max_iterations=5,
    )

    # Create task with skills in metadata
    task = AgentTask(
        id=uuid4(),
        title="Math with skill",
        description="Solve: 42 * 17 + 99",
        query="Solve this math problem: 42 * 17 + 99. Activate the math skill first.",
        user_id="test-user",
        workspace_id="test-workspace",
        agent_id=uuid4(),
        status="pending",
        metadata={
            "instruction": (
                "You are a helpful agent. You MUST use activate_skill to load "
                "skill instructions before attempting any task."
            ),
            "skills": [
                {
                    "name": "math-methodology",
                    "description": "Step-by-step methodology for solving math problems",
                    "content": (
                        "## Math Methodology\n"
                        "1. Break the expression into parts\n"
                        "2. Solve step by step\n"
                        "3. Verify by working backwards\n"
                        "4. State final answer as: ANSWER: <number>"
                    ),
                    "files": [],
                },
                {
                    "name": "js-formatter",
                    "description": "Format JavaScript code with Prettier",
                    "content": "Use prettier to format JS files.",
                    "files": [],
                },
            ],
        },
    )

    print(f"\nTask: {task.query}")
    print(f"Skills: {[s['name'] for s in task.metadata['skills']]}")
    print(f"Execution engine: DirectTaskManager (in-process)")
    print()

    # Submit — runs synchronously, no Temporal
    result = await manager.submit_task(task)

    print(f"\n{'=' * 60}")
    print("RESULTS")
    print(f"{'=' * 60}")
    print(f"Status: {result.status}")
    print(f"Result: {result.result}")

    # Verify via interface methods
    status = await manager.get_task_status(task.id)
    stored_result = await manager.get_task_result(task.id)
    all_tasks = await manager.list_tasks()

    print(f"\nget_task_status(): {status}")
    print(f"get_task_result(): {stored_result}")
    print(f"list_tasks() count: {len(all_tasks)}")

    # Assertions
    passed = 0
    total = 3

    if result.status == "completed":
        print("\n  PASS: Task completed")
        passed += 1
    else:
        print(f"\n  FAIL: Task status: {result.status}")

    if result.result and "response" in result.result:
        print(f"  PASS: Got response: {str(result.result['response'])[:100]}")
        passed += 1
    else:
        print(f"  FAIL: No response in result")

    if status == "completed":
        print("  PASS: get_task_status() returns completed")
        passed += 1
    else:
        print(f"  FAIL: get_task_status() returns {status}")

    print(f"\n  Score: {passed}/{total}")
    print(f"\n  Same interface as TemporalTaskManager. Zero infrastructure.")


if __name__ == "__main__":
    asyncio.run(main())
