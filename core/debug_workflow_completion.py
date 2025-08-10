#!/usr/bin/env python3
"""Debug workflow completion issue - test JSON parsing and tool execution flow.
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

# Global variables to track execution
execution_log = []

def create_debug_activities():
    """Create debug activities that log all interactions."""

    @activity.defn
    async def build_agent_config_activity(*args, **kwargs):
        execution_log.append("build_agent_config_activity called")
        return {
            "id": "debug-agent",
            "name": "Debug Agent",
            "description": "Debug agent for completion testing",
            "instruction": "Complete tasks and debug issues",
            "model_id": "debug-model-id",
            "tools_config": {},
            "events_config": {},
            "planning": False,
        }

    @activity.defn
    async def discover_available_tools_activity(*args, **kwargs):
        execution_log.append("discover_available_tools_activity called")
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
    async def call_llm_activity(*args, **kwargs):
        execution_log.append("call_llm_activity called")
        logger.info("🤖 LLM Activity: Creating completion response")

        # Create a proper tool call with JSON arguments
        tool_call_args = {
            "result": "Debug task completed successfully - testing completion detection",
            "success": True
        }

        logger.info(f"🔧 Tool call arguments: {tool_call_args}")
        logger.info(f"🔧 JSON serialized: {json.dumps(tool_call_args)}")

        response = {
            "role": "assistant",
            "content": "I'll complete this debug task now.",
            "tool_calls": [
                {
                    "id": "debug_completion_call",
                    "type": "function",
                    "function": {
                        "name": "task_complete",
                        "arguments": json.dumps(tool_call_args)  # Properly serialize JSON
                    }
                }
            ],
            "cost": 0.005,
            "usage": {"prompt_tokens": 50, "completion_tokens": 25, "total_tokens": 75}
        }

        logger.info(f"🔧 Full LLM response: {json.dumps(response, indent=2)}")
        return response

    @activity.defn
    async def execute_mcp_tool_activity(tool_name: str, tool_args: dict, *args, **kwargs):
        execution_log.append(f"execute_mcp_tool_activity called: {tool_name}")
        logger.info(f"🛠️ Tool Execution: {tool_name}")
        logger.info(f"🛠️ Tool Args Received: {tool_args}")
        logger.info(f"🛠️ Tool Args Type: {type(tool_args)}")

        if tool_name == "task_complete":
            # Create the exact response structure expected by the workflow
            result = {
                "success": tool_args.get("success", True),
                "completed": tool_args.get("success", True),  # Also set completed flag
                "result": tool_args.get("result", "Task completed")
            }

            logger.info(f"🛠️ Tool Result: {result}")
            logger.info(f"🛠️ success field: {result.get('success')}")
            logger.info(f"🛠️ completed field: {result.get('completed')}")

            execution_log.append(f"task_complete executed with result: {result}")
            return result

        return {"success": True, "result": f"Executed {tool_name}"}

    @activity.defn
    async def evaluate_goal_progress_activity(*args, **kwargs):
        execution_log.append("evaluate_goal_progress_activity called")
        return {"goal_achieved": False, "final_response": None, "confidence": 0.5}

    @activity.defn
    async def publish_workflow_events_activity(*args, **kwargs):
        execution_log.append("publish_workflow_events_activity called")
        return True

    return [
        build_agent_config_activity,
        discover_available_tools_activity,
        call_llm_activity,
        execute_mcp_tool_activity,
        evaluate_goal_progress_activity,
        publish_workflow_events_activity,
    ]

async def debug_workflow_completion():
    """Debug workflow completion detection."""
    global execution_log
    execution_log = []

    logger.info("🔍 Starting Workflow Completion Debug")
    logger.info("=" * 60)

    # Create test environment
    env = await WorkflowEnvironment.start_time_skipping()

    try:
        # Create debug activities and worker
        activities = create_debug_activities()
        worker = Worker(
            env.client,
            task_queue="debug-completion",
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
                user_id="debug-user",
                task_query="Debug task completion detection",
                budget_usd=1.0
            )

            logger.info(f"🎯 Task ID: {task_id}")
            logger.info(f"🤖 Agent ID: {agent_id}")

            # Execute workflow
            workflow_handle = await env.client.start_workflow(
                AgentExecutionWorkflow.run,
                request,
                id=f"debug-completion-{task_id}",
                task_queue="debug-completion",
            )

            logger.info("🚀 Workflow started, waiting for completion...")

            # Add timeout to detect hanging
            try:
                result = await asyncio.wait_for(workflow_handle.result(), timeout=30.0)

                logger.info("✅ Workflow completed!")
                logger.info(f"📊 Success: {result.success}")
                logger.info(f"📊 Final Response: {result.final_response}")
                logger.info(f"📊 Iterations: {result.reasoning_iterations_used}")
                logger.info(f"📊 Cost: ${result.total_cost}")

                return result.success

            except TimeoutError:
                logger.error("❌ WORKFLOW TIMED OUT - Never completed!")
                logger.error("This confirms the workflow completion detection is broken")
                return False

    finally:
        await env.shutdown()

        # Print execution log
        logger.info("\n📜 Execution Log:")
        for i, entry in enumerate(execution_log, 1):
            logger.info(f"  {i}. {entry}")

async def debug_json_parsing():
    """Test JSON parsing specifically."""
    logger.info("\n🧪 Testing JSON Parsing")
    logger.info("-" * 40)

    # Test the exact JSON structure from LLM response
    test_json = json.dumps({
        "result": "Test completion result",
        "success": True
    })

    logger.info(f"Original JSON: {test_json}")

    try:
        parsed = json.loads(test_json)
        logger.info(f"Parsed JSON: {parsed}")
        logger.info(f"Success field: {parsed.get('success')}")
        logger.info(f"Success type: {type(parsed.get('success'))}")

        # Test the boolean evaluation
        is_successful = parsed.get("success", False) or parsed.get("completed", False)
        logger.info(f"is_successful evaluation: {is_successful}")

        return True
    except Exception as e:
        logger.error(f"JSON parsing failed: {e}")
        return False

if __name__ == "__main__":
    # Run debug tests
    logger.info("🚨 DEBUGGING WORKFLOW COMPLETION ISSUE")
    logger.info("=" * 80)

    # Test JSON parsing first
    json_success = asyncio.run(debug_json_parsing())

    # Test workflow execution
    workflow_success = asyncio.run(debug_workflow_completion())

    print("\n" + "=" * 80)
    print("🔍 DEBUG RESULTS:")
    print(f"  JSON Parsing: {'✅ OK' if json_success else '❌ FAILED'}")
    print(f"  Workflow Completion: {'✅ OK' if workflow_success else '❌ FAILED'}")

    if not workflow_success:
        print("\n🚨 WORKFLOW COMPLETION IS BROKEN!")
        print("The workflow is not detecting task_complete properly.")
        print("Check the execution log above for clues.")
    else:
        print("\n✅ Workflow completion is working correctly.")

    exit(0 if (json_success and workflow_success) else 1)
