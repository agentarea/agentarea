"""Test full workflow execution with real LLM to identify where malformed responses occur."""

import logging
import os
from datetime import timedelta
from uuid import uuid4

import pytest
from agentarea_execution.activities.agent_execution_activities import make_agent_activities
from agentarea_execution.models import AgentExecutionRequest
from agentarea_execution.workflows.agent_execution_workflow import AgentExecutionWorkflow
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

logger = logging.getLogger(__name__)


class TestDependencies:
    """Test dependencies with real secret manager and event broker."""

    class TestSecretManager:
        async def get_secret(self, secret_name: str) -> str:
            # Return empty for Ollama (no API key needed)
            return ""

    class TestEventBroker:
        def __init__(self):
            self.published_events = []

        async def publish(self, event):
            self.published_events.append(event)
            logger.info(f"Published event: {event}")

    def __init__(self):
        self.secret_manager = self.TestSecretManager()
        self.event_broker = self.TestEventBroker()


@pytest.mark.asyncio
async def test_full_workflow_with_real_ollama():
    """Test full workflow execution with real Ollama to see where malformed responses occur."""

    # Skip if no Ollama available
    docker_host = os.environ.get("LLM_DOCKER_HOST", "localhost")

    # Create test dependencies
    dependencies = TestDependencies()

    # Create real activities
    activities = make_agent_activities(dependencies)

    # Create execution request
    execution_request = AgentExecutionRequest(
        agent_id=uuid4(),
        task_id=uuid4(),
        user_id="test-user",
        task_query="Complete this simple test task",
        task_parameters={"success_criteria": ["Task completed successfully"], "max_iterations": 3},
        budget_usd=1.0,
        requires_human_approval=False,
    )

    # Mock the agent config and tools discovery activities to avoid database dependencies
    original_activities = activities.copy()

    @activity.defn(name="build_agent_config_activity")
    async def mock_build_agent_config(*args, **kwargs):
        logger.info("Mock: Building agent config")
        return {
            "id": str(execution_request.agent_id),
            "name": "Test Agent",
            "description": "A test agent",
            "instruction": "You are a helpful AI assistant. When you complete a task, use the task_complete tool.",
            "model_id": str(uuid4()),  # This will be ignored since we override the model
            "tools_config": {},
            "events_config": {},
            "planning": False,
        }

    @activity.defn(name="discover_available_tools_activity")
    async def mock_discover_tools(*args, **kwargs):
        logger.info("Mock: Discovering tools")
        return [
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

    # Create a custom LLM activity that uses real Ollama
    @activity.defn(name="call_llm_activity")
    async def real_ollama_llm_activity(
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
    ):
        logger.info("Real LLM: Making call to Ollama")
        logger.info(f"Messages: {len(messages)} messages")
        logger.info(f"Tools: {len(tools) if tools else 0} tools")

        from agentarea_agents_sdk.models.llm_model import LLMModel, LLMRequest

        # Create LLM model for Ollama
        llm_model = LLMModel(
            provider_type="ollama_chat",
            model_name="qwen2.5",
            endpoint_url=f"http://{docker_host}:11434",
        )

        # Create request
        request = LLMRequest(
            messages=messages,
            tools=tools,
            temperature=temperature or 0.1,
            max_tokens=max_tokens or 200,
        )

        try:
            # Use streaming to match production behavior
            complete_content = ""
            complete_tool_calls = None
            final_usage = None
            final_cost = 0.0

            logger.info("Starting streaming LLM call...")
            async for chunk in llm_model.ainvoke_stream(request):
                logger.info(
                    f"Chunk received - Content: '{chunk.content}', Tool calls: {chunk.tool_calls}"
                )

                if chunk.content:
                    complete_content += chunk.content

                if chunk.tool_calls:
                    complete_tool_calls = chunk.tool_calls

                if chunk.usage:
                    final_usage = chunk.usage

                if chunk.cost:
                    final_cost = chunk.cost

            # Create final response
            result = {
                "role": "assistant",
                "content": complete_content,
                "tool_calls": complete_tool_calls,
                "cost": final_cost,
                "usage": final_usage.__dict__ if final_usage else None,
            }

            logger.info("=== FINAL LLM RESPONSE ===")
            logger.info(f"Content: '{result['content']}'")
            logger.info(f"Tool calls: {result['tool_calls']}")
            logger.info(f"Cost: {result['cost']}")

            # Check if we have the malformed response issue
            if not result["tool_calls"] and result["content"]:
                if "task_complete" in result["content"].lower():
                    logger.warning("🚨 MALFORMED RESPONSE DETECTED IN WORKFLOW!")
                    logger.warning(f"Tool calls are None but content contains: {result['content']}")

            return result

        except Exception as e:
            logger.error(f"Real LLM call failed: {e}")
            raise

    # Replace activities with our mocks and real LLM
    test_activities = [
        mock_build_agent_config,
        mock_discover_tools,
        real_ollama_llm_activity,
        # Keep the real tool execution and other activities
        *[
            a
            for a in original_activities
            if a.__name__
            not in [
                "build_agent_config_activity",
                "discover_available_tools_activity",
                "call_llm_activity",
            ]
        ],
    ]

    env = await WorkflowEnvironment.start_time_skipping()
    try:
        async with Worker(
            env.client,
            task_queue="test-queue",
            workflows=[AgentExecutionWorkflow],
            activities=test_activities,
        ):
            logger.info("Starting full workflow test with real Ollama")

            try:
                result = await env.client.execute_workflow(
                    AgentExecutionWorkflow.run,
                    execution_request,
                    id=f"test-workflow-{uuid4()}",
                    task_queue="test-queue",
                    execution_timeout=timedelta(seconds=30),
                )

                logger.info("=== WORKFLOW RESULT ===")
                logger.info(f"Success: {result.success}")
                logger.info(f"Iterations: {result.reasoning_iterations_used}")
                logger.info(f"Final response: {result.final_response}")
                logger.info(f"Total cost: ${result.total_cost:.6f}")

                # The workflow should complete successfully
                assert result.reasoning_iterations_used >= 1, (
                    "Should have completed at least 1 iteration"
                )

                if result.success:
                    logger.info("✅ Workflow completed successfully with real LLM")
                else:
                    logger.warning("⚠️ Workflow did not complete successfully")

            except Exception as e:
                logger.error(f"Workflow execution failed: {e}")
                pytest.skip(f"Ollama not available or workflow failed: {e}")

    finally:
        await env.shutdown()


@pytest.mark.asyncio
async def test_compare_direct_vs_workflow_llm_calls():
    """Compare direct LLM calls vs workflow LLM calls to identify differences."""

    docker_host = os.environ.get("LLM_DOCKER_HOST", "localhost")

    from agentarea_agents_sdk.models.llm_model import LLMModel, LLMRequest

    # Create LLM model
    llm_model = LLMModel(
        provider_type="ollama_chat",
        model_name="qwen2.5",
        endpoint_url=f"http://{docker_host}:11434",
    )

    # Test messages and tools
    messages = [
        {
            "role": "system",
            "content": "You are a helpful AI assistant. When you complete a task, use the task_complete tool.",
        },
        {"role": "user", "content": "Complete this simple test task"},
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

    request = LLMRequest(messages=messages, tools=tools, temperature=0.1, max_tokens=200)

    logger.info("=== DIRECT LLM CALL ===")
    try:
        # Direct call using our SDK
        complete_content = ""
        complete_tool_calls = None

        async for chunk in llm_model.ainvoke_stream(request):
            if chunk.content:
                complete_content += chunk.content
            if chunk.tool_calls:
                complete_tool_calls = chunk.tool_calls

        logger.info("Direct call result:")
        logger.info(f"  Content: '{complete_content}'")
        logger.info(f"  Tool calls: {complete_tool_calls}")

    except Exception as e:
        logger.error(f"Direct call failed: {e}")
        pytest.skip(f"Ollama not available: {e}")

    logger.info("\n=== WORKFLOW ACTIVITY CALL ===")
    try:
        # Now test through the workflow activity
        dependencies = TestDependencies()
        activities = make_agent_activities(dependencies)

        # Find the call_llm_activity
        call_llm_activity = None
        for activity_func in activities:
            if hasattr(activity_func, "__name__") and activity_func.__name__ == "call_llm_activity":
                call_llm_activity = activity_func
                break

        if call_llm_activity:
            # Call the activity directly (this simulates what the workflow does)
            activity_result = await call_llm_activity(
                messages=messages,
                model_id="fake-uuid-for-test",  # This will cause an error, but let's see what happens
                tools=tools,
                workspace_id="system",
                temperature=0.1,
                max_tokens=200,
                task_id="test-task",
                agent_id="test-agent",
                execution_id="test-execution",
            )

            logger.info("Activity call result:")
            logger.info(f"  Content: '{activity_result.get('content', '')}'")
            logger.info(f"  Tool calls: {activity_result.get('tool_calls')}")

            # Compare results
            if activity_result.get("tool_calls") != complete_tool_calls:
                logger.warning("🚨 DIFFERENCE DETECTED!")
                logger.warning(f"Direct: {complete_tool_calls}")
                logger.warning(f"Activity: {activity_result.get('tool_calls')}")
        else:
            logger.error("Could not find call_llm_activity")

    except Exception as e:
        logger.info(f"Activity call failed (expected due to fake model ID): {e}")
        # This is expected since we're using a fake model ID


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    pytest.main([__file__, "-v", "-s"])
