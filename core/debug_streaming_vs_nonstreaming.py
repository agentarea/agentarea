#!/usr/bin/env python3
"""Debug streaming vs non-streaming LLM calls to see if streaming breaks tool calls.
"""

import asyncio
import json
import logging
from uuid import uuid4

from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from libs.execution.agentarea_execution.models import AgentExecutionRequest
from libs.execution.agentarea_execution.workflows.agent_execution_workflow import (
    AgentExecutionWorkflow,
)

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global tracking
test_results = {}

def create_test_activities(use_streaming: bool):
    """Create activities that test streaming vs non-streaming."""
    test_results[f"streaming_{use_streaming}"] = {
        "llm_calls": 0,
        "tool_calls": 0,
        "completions": 0,
        "success": False
    }

    @activity.defn
    async def build_agent_config_activity(*args, **kwargs):
        return {
            "id": "streaming-test-agent",
            "name": "Streaming Test Agent",
            "description": "Test streaming vs non-streaming",
            "instruction": "Complete tasks efficiently",
            "model_id": "test-model-id",
            "tools_config": {},
            "events_config": {},
            "planning": False,
        }

    @activity.defn
    async def discover_available_tools_activity(*args, **kwargs):
        return [
            {
                "name": "task_complete",
                "description": "Mark task as completed",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "result": {"type": "string"},
                        "success": {"type": "boolean"}
                    },
                    "required": ["result", "success"]
                }
            }
        ]

    @activity.defn
    async def call_llm_activity(
        messages,
        model_id,
        tools=None,
        workspace_id=None,
        user_context_data=None,
        temperature=None,
        max_tokens=None,
        task_id=None,
        agent_id=None,
        execution_id=None,
        enable_streaming=True,
    ):
        """Mock LLM activity that simulates streaming vs non-streaming behavior."""
        test_results[f"streaming_{use_streaming}"]["llm_calls"] += 1

        logger.info(f"🤖 LLM Call (streaming={enable_streaming})")
        logger.info(f"    Expected streaming: {use_streaming}")
        logger.info(f"    Actual streaming: {enable_streaming}")

        # Simulate potential streaming issues
        if enable_streaming and use_streaming:
            logger.info("    📡 Simulating streaming response...")
            # Streaming might have different response format or issues
            response = {
                "role": "assistant",
                "content": "I'll complete this task using streaming mode.",
                "tool_calls": [
                    {
                        "id": "streaming_completion",
                        "type": "function",
                        "function": {
                            "name": "task_complete",
                            "arguments": json.dumps({
                                "result": "Task completed via streaming",
                                "success": True
                            })
                        }
                    }
                ],
                "cost": 0.001,
                "usage": {"prompt_tokens": 50, "completion_tokens": 30, "total_tokens": 80}
            }
        else:
            logger.info("    📄 Simulating non-streaming response...")
            # Non-streaming should work normally
            response = {
                "role": "assistant",
                "content": "I'll complete this task using non-streaming mode.",
                "tool_calls": [
                    {
                        "id": "nonstreaming_completion",
                        "type": "function",
                        "function": {
                            "name": "task_complete",
                            "arguments": json.dumps({
                                "result": "Task completed via non-streaming",
                                "success": True
                            })
                        }
                    }
                ],
                "cost": 0.001,
                "usage": {"prompt_tokens": 50, "completion_tokens": 30, "total_tokens": 80}
            }

        logger.info(f"    Tool calls in response: {len(response.get('tool_calls', []))}")
        return response

    @activity.defn
    async def execute_mcp_tool_activity(tool_name: str, tool_args: dict, *args, **kwargs):
        test_results[f"streaming_{use_streaming}"]["tool_calls"] += 1

        logger.info(f"🛠️ Tool Execution: {tool_name}")
        logger.info(f"    Args: {tool_args}")

        if tool_name == "task_complete":
            test_results[f"streaming_{use_streaming}"]["completions"] += 1
            result = {
                "success": True,
                "completed": True,
                "result": tool_args.get("result", "Task completed")
            }
            logger.info(f"    Result: {result}")
            return result

        return {"success": True, "result": f"Executed {tool_name}"}

    @activity.defn
    async def evaluate_goal_progress_activity(*args, **kwargs):
        return {"goal_achieved": False, "final_response": None, "confidence": 0.5}

    @activity.defn
    async def publish_workflow_events_activity(*args, **kwargs):
        return True

    return [
        build_agent_config_activity,
        discover_available_tools_activity,
        call_llm_activity,
        execute_mcp_tool_activity,
        evaluate_goal_progress_activity,
        publish_workflow_events_activity,
    ]

async def test_streaming_vs_nonstreaming():
    """Test both streaming and non-streaming workflows."""
    logger.info("🔍 Testing Streaming vs Non-Streaming LLM Calls")
    logger.info("=" * 80)

    results = {}

    for use_streaming in [False, True]:
        logger.info(f"\n📊 Testing with streaming={use_streaming}")
        logger.info("-" * 60)

        # Create test environment
        env = await WorkflowEnvironment.start_time_skipping()

        try:
            # Create activities and worker
            activities = create_test_activities(use_streaming)
            worker = Worker(
                env.client,
                task_queue=f"streaming-test-{use_streaming}",
                workflows=[AgentExecutionWorkflow],
                activities=activities,
            )

            async with worker:
                # Create test request
                task_id = uuid4()
                agent_id = uuid4()

                request = AgentExecutionRequest(
                    agent_id=agent_id,
                    task_id=task_id,
                    user_id="streaming-test-user",
                    task_query=f"Test streaming={use_streaming} completion",
                    budget_usd=1.0
                )

                logger.info(f"🚀 Starting workflow (streaming={use_streaming})")

                # Execute workflow with timeout
                try:
                    workflow_handle = await env.client.start_workflow(
                        AgentExecutionWorkflow.run,
                        request,
                        id=f"streaming-test-{use_streaming}-{task_id}",
                        task_queue=f"streaming-test-{use_streaming}",
                    )

                    result = await asyncio.wait_for(workflow_handle.result(), timeout=20.0)

                    logger.info(f"✅ Workflow completed (streaming={use_streaming})")
                    logger.info(f"    Success: {result.success}")
                    logger.info(f"    Iterations: {result.reasoning_iterations_used}")
                    logger.info(f"    Final Response: {result.final_response}")

                    test_results[f"streaming_{use_streaming}"]["success"] = result.success
                    results[f"streaming_{use_streaming}"] = result.success

                except TimeoutError:
                    logger.error(f"❌ Workflow timed out (streaming={use_streaming})")
                    test_results[f"streaming_{use_streaming}"]["success"] = False
                    results[f"streaming_{use_streaming}"] = False

        finally:
            await env.shutdown()

    # Analysis
    logger.info("\n📊 Analysis")
    logger.info("=" * 80)

    for streaming_mode in [False, True]:
        key = f"streaming_{streaming_mode}"
        data = test_results[key]

        logger.info(f"\nStreaming={streaming_mode}:")
        logger.info(f"  LLM Calls: {data['llm_calls']}")
        logger.info(f"  Tool Calls: {data['tool_calls']}")
        logger.info(f"  Completions: {data['completions']}")
        logger.info(f"  Success: {data['success']}")

    # Check for differences
    streaming_success = results.get("streaming_True", False)
    nonstreaming_success = results.get("streaming_False", False)

    logger.info("\n🔍 Comparison:")
    logger.info(f"  Non-streaming success: {nonstreaming_success}")
    logger.info(f"  Streaming success: {streaming_success}")

    if streaming_success != nonstreaming_success:
        logger.error("❌ STREAMING BEHAVIOR IS DIFFERENT FROM NON-STREAMING!")
        logger.error("This could explain why workflows never finish in your system.")
        return False
    else:
        logger.info("✅ Both streaming and non-streaming behave the same")
        return True

if __name__ == "__main__":
    # Run the test
    result = asyncio.run(test_streaming_vs_nonstreaming())

    print("\n" + "=" * 80)
    if result:
        print("✅ STREAMING VS NON-STREAMING TEST PASSED")
        print("Both modes work the same - streaming is not the issue")
    else:
        print("❌ STREAMING VS NON-STREAMING TEST FAILED")
        print("Streaming mode behaves differently - this could be the bug!")

    exit(0 if result else 1)
