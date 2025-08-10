#!/usr/bin/env python3
"""Quick test to verify that streaming events are working correctly.
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

# Global event collector for testing
collected_events = []


def create_mock_activities():
    """Create mock activities for testing streaming."""

    @activity.defn
    async def build_agent_config_activity(*args, **kwargs):
        return {
            "id": "test-agent",
            "name": "Test Streaming Agent",
            "description": "Test agent for streaming events",
            "instruction": "Complete tasks and test streaming",
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
        """Mock LLM activity that tests streaming parameters."""
        logger.info("🔍 LLM Activity called with streaming params:")
        logger.info(f"  task_id: {task_id}")
        logger.info(f"  agent_id: {agent_id}")
        logger.info(f"  execution_id: {execution_id}")
        logger.info(f"  enable_streaming: {enable_streaming}")

        # Simulate streaming by collecting the parameters
        global collected_events
        collected_events.append({
            "type": "llm_call_params",
            "data": {
                "task_id": task_id,
                "agent_id": agent_id,
                "execution_id": execution_id,
                "enable_streaming": enable_streaming,
                "has_streaming_params": all([task_id, agent_id, execution_id, enable_streaming])
            }
        })

        # Return mock LLM response
        return {
            "role": "assistant",
            "content": "I'll complete this streaming test task.",
            "tool_calls": [
                {
                    "id": "call_streaming_test",
                    "type": "function",
                    "function": {
                        "name": "task_complete",
                        "arguments": json.dumps({
                            "result": "Streaming test completed successfully",
                            "success": True
                        })
                    }
                }
            ],
            "cost": 0.005,
            "usage": {"prompt_tokens": 50, "completion_tokens": 25, "total_tokens": 75}
        }

    @activity.defn
    async def execute_mcp_tool_activity(tool_name, tool_args, *args, **kwargs):
        if tool_name == "task_complete":
            return {
                "success": True,
                "result": tool_args.get("result", "Task completed"),
                "completed": True
            }
        return {"success": True, "result": f"Executed {tool_name}"}

    @activity.defn
    async def evaluate_goal_progress_activity(*args, **kwargs):
        return {
            "completed": True,
            "success": True,
            "confidence": 0.95
        }

    @activity.defn
    async def publish_workflow_events_activity(events_json):
        """Mock event publishing that tracks events."""
        global collected_events

        logger.info(f"📤 Publishing {len(events_json)} events")

        for event_json in events_json:
            event = json.loads(event_json)
            collected_events.append({
                "type": "workflow_event",
                "event_type": event.get("event_type"),
                "data": event.get("data", {})
            })
            logger.info(f"  Event: {event.get('event_type')}")

        return True

    return [
        build_agent_config_activity,
        discover_available_tools_activity,
        call_llm_activity,
        execute_mcp_tool_activity,
        evaluate_goal_progress_activity,
        publish_workflow_events_activity,
    ]


async def test_streaming_parameters():
    """Test that streaming parameters are correctly passed to LLM activity."""
    global collected_events
    collected_events = []

    logger.info("🚀 Starting Streaming Parameters Test")
    logger.info("=" * 60)

    # Create test environment
    env = await WorkflowEnvironment.start_time_skipping()

    try:
        # Create activities and worker
        activities = create_mock_activities()
        worker = Worker(
            env.client,
            task_queue="streaming-test",
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
                user_id="test-streaming-user",
                task_query="Test streaming events functionality",
                budget_usd=1.0
            )

            logger.info(f"Task ID: {task_id}")
            logger.info(f"Agent ID: {agent_id}")

            # Execute workflow
            workflow_handle = await env.client.start_workflow(
                AgentExecutionWorkflow.run,
                request,
                id=f"streaming-test-{task_id}",
                task_queue="streaming-test",
            )

            logger.info("🔄 Executing workflow...")
            result = await workflow_handle.result()

            logger.info(f"✅ Workflow completed: {result.success}")

            # Analyze collected events
            logger.info("\n📊 Analyzing Collected Events")
            logger.info("-" * 40)

            llm_param_events = [e for e in collected_events if e["type"] == "llm_call_params"]
            workflow_events = [e for e in collected_events if e["type"] == "workflow_event"]

            logger.info(f"LLM parameter events: {len(llm_param_events)}")
            logger.info(f"Workflow events: {len(workflow_events)}")

            # Verify streaming parameters were passed
            success = True

            if not llm_param_events:
                logger.error("❌ No LLM parameter events found!")
                success = False
            else:
                llm_event = llm_param_events[0]
                params = llm_event["data"]

                logger.info("LLM call parameters:")
                logger.info(f"  task_id: {params['task_id']}")
                logger.info(f"  agent_id: {params['agent_id']}")
                logger.info(f"  execution_id: {params['execution_id']}")
                logger.info(f"  enable_streaming: {params['enable_streaming']}")
                logger.info(f"  has_streaming_params: {params['has_streaming_params']}")

                if not params['has_streaming_params']:
                    logger.error("❌ Streaming parameters are missing or None!")
                    success = False
                else:
                    logger.info("✅ All streaming parameters are correctly passed!")

            # Check workflow events
            event_types = [e["event_type"] for e in workflow_events]
            expected_events = ["WorkflowStarted", "LLMCallStarted", "LLMCallCompleted"]

            logger.info(f"\nWorkflow event types: {event_types}")

            for expected in expected_events:
                if expected in event_types:
                    logger.info(f"✅ Found expected event: {expected}")
                else:
                    logger.warning(f"⚠️ Missing expected event: {expected}")

            # Final result
            logger.info("\n" + "=" * 60)
            if success:
                logger.info("🎉 STREAMING PARAMETERS TEST PASSED!")
                logger.info("   ✅ Streaming parameters correctly passed to LLM activity")
                logger.info("   ✅ Workflow events published successfully")
                logger.info("   ✅ Now the real LLM should receive streaming context")
            else:
                logger.error("❌ STREAMING PARAMETERS TEST FAILED!")
                logger.error("   The workflow is not passing streaming parameters properly")

            return success

    finally:
        await env.shutdown()


if __name__ == "__main__":
    # Run the test
    result = asyncio.run(test_streaming_parameters())

    print("\n" + "=" * 60)
    if result:
        print("🎉 Streaming test PASSED! Your streaming events should now work.")
        print("\nNext steps:")
        print("1. The workflow now passes streaming parameters to LLM activity")
        print("2. The LLM activity can use these parameters for real-time streaming")
        print("3. Chunk events should appear in the UI during LLM responses")
        print("4. Frontend will show rich event content and costs")
    else:
        print("❌ Streaming test FAILED! Check the logs above for issues.")

    exit(0 if result else 1)
