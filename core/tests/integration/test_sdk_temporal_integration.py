"""Test integration between agentarea-agents-sdk and Temporal workflow."""

import logging
from datetime import timedelta
from uuid import uuid4

import pytest
from agentarea_execution.activities.agent_execution_activities import make_agent_activities
from agentarea_execution.models import AgentExecutionRequest
from agentarea_execution.workflows.agent_execution_workflow import AgentExecutionWorkflow
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

logger = logging.getLogger(__name__)


class SDKTemporalTestDependencies:
    """Dependencies for testing SDK integration with Temporal."""

    class TestSecretManager:
        async def get_secret(self, secret_name: str) -> str:
            return ""  # No API key needed for Ollama

    class TestEventBroker:
        def __init__(self):
            self.published_events = []
            self.broker = self

        async def publish(self, event):
            self.published_events.append(event)
            logger.debug(f"Event published: {getattr(event, 'event_type', 'unknown')}")

    def __init__(self):
        self.secret_manager = self.TestSecretManager()
        self.event_broker = self.TestEventBroker()


@pytest.mark.asyncio
async def test_sdk_temporal_integration_single_tool_call():
    """Test that the SDK properly integrates with Temporal for single tool calls."""

    logger.info("🧪 Testing SDK + Temporal integration with single tool call")

    # Create dependencies
    dependencies = SDKTemporalTestDependencies()

    # Create real activities
    activities = make_agent_activities(dependencies)

    # Mock the database-dependent activities but use real LLM
    from uuid import UUID

    from temporalio import activity

    @activity.defn(name="build_agent_config_activity")
    async def mock_build_agent_config(agent_id: UUID, user_context_data: dict, **kwargs):
        logger.info(f"Mock: Building agent config for {agent_id}")
        return {
            "id": str(agent_id),
            "name": "SDK Test Agent",
            "instruction": "You are a helpful assistant. Use the calculate tool for math problems. When done, use task_complete.",
            "model_id": "66666666-6666-6666-6666-666666666666",
            "tools_config": {},
            "events_config": {},
            "planning": False,
        }

    @activity.defn(name="discover_available_tools_activity")
    async def mock_discover_tools(agent_id: UUID, user_context_data: dict, **kwargs):
        logger.info(f"Mock: Discovering tools for {agent_id}")
        return [
            {
                "type": "function",
                "function": {
                    "name": "calculate",
                    "description": "Perform a mathematical calculation",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "expression": {
                                "type": "string",
                                "description": "Mathematical expression to evaluate",
                            }
                        },
                        "required": ["expression"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "task_complete",
                    "description": "Mark task as completed",
                    "parameters": {
                        "type": "object",
                        "properties": {"result": {"type": "string", "description": "Final result"}},
                        "required": [],
                    },
                },
            },
        ]

    # Create a custom LLM activity that uses the SDK directly
    @activity.defn(name="call_llm_activity")
    async def sdk_llm_activity(
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
        logger.info("🚀 Using SDK LLM model directly in Temporal activity")
        logger.info(f"📝 Messages: {len(messages)} messages")
        logger.info(f"🔧 Tools: {len(tools) if tools else 0} tools")

        from agentarea_agents_sdk.models.llm_model import LLMModel, LLMRequest

        # Use the SDK LLM model directly
        model = LLMModel(
            provider_type="ollama_chat", model_name="qwen2.5", endpoint_url="http://localhost:11434"
        )

        request = LLMRequest(
            messages=messages,
            tools=tools,
            temperature=temperature or 0.1,
            max_tokens=max_tokens or 300,
        )

        try:
            response = await model.complete(request)

            logger.info("=" * 50)
            logger.info("🎯 SDK LLM RESPONSE IN TEMPORAL")
            logger.info("=" * 50)
            logger.info(f"📝 Content: '{response.content}'")
            logger.info(f"🔧 Tool calls: {response.tool_calls}")
            logger.info(f"💰 Cost: ${response.cost:.6f}")

            # Convert SDK response to Temporal workflow format
            result = {
                "role": response.role,
                "content": response.content,
                "tool_calls": response.tool_calls,
                "cost": response.cost,
                "usage": response.usage.__dict__ if response.usage else None,
            }

            if response.tool_calls:
                logger.info("✅ SDK returned proper tool calls to Temporal")
                for i, tc in enumerate(response.tool_calls):
                    logger.info(f"   Tool {i}: {tc['function']['name']}")
            else:
                logger.warning("⚠️ No tool calls returned from SDK")

            logger.info("=" * 50)

            return result

        except Exception as e:
            logger.error(f"❌ SDK LLM call failed: {e}")
            raise

    # Replace activities with our mocked versions
    real_activities = []
    for activity_func in activities:
        activity_name = getattr(activity_func, "__name__", "")
        if "build_agent_config" in activity_name:
            real_activities.append(mock_build_agent_config)
        elif "discover_available_tools" in activity_name:
            real_activities.append(mock_discover_tools)
        elif "call_llm" in activity_name:
            real_activities.append(sdk_llm_activity)
        else:
            real_activities.append(activity_func)

    # Create execution request
    execution_request = AgentExecutionRequest(
        agent_id="12345678-1234-5678-1234-567812345678",
        task_id=str(uuid4()),
        user_id="test-user-id",
        task_query="What is 25 + 17?",  # Simple math problem
        task_parameters={"success_criteria": ["Calculate the sum correctly"], "max_iterations": 2},
        budget_usd=1.0,
        requires_human_approval=False,
    )

    logger.info(f"🤖 Agent ID: {execution_request.agent_id}")
    logger.info(f"📝 Task: '{execution_request.task_query}'")
    logger.info(f"🔄 Max iterations: {execution_request.task_parameters['max_iterations']}")

    env = await WorkflowEnvironment.start_time_skipping()
    try:
        async with Worker(
            env.client,
            task_queue="sdk-temporal-test-queue",
            workflows=[AgentExecutionWorkflow],
            activities=real_activities,
            debug_mode=True,
        ):
            logger.info("🚀 Starting SDK + Temporal workflow execution...")

            try:
                result = await env.client.execute_workflow(
                    AgentExecutionWorkflow.run,
                    execution_request,
                    id=f"sdk-temporal-test-{uuid4()}",
                    task_queue="sdk-temporal-test-queue",
                    execution_timeout=timedelta(minutes=2),
                )

                logger.info("=" * 60)
                logger.info("🎉 SDK + TEMPORAL INTEGRATION SUCCESS!")
                logger.info("=" * 60)
                logger.info(f"✅ Success: {result.success}")
                logger.info(f"📊 Iterations: {result.reasoning_iterations_used}")
                logger.info(f"💬 Final response: {result.final_response}")
                logger.info(f"💰 Total cost: ${result.total_cost:.6f}")
                logger.info(f"📝 Conversation messages: {len(result.conversation_history)}")

                # Analyze the conversation for proper tool usage
                tool_calls_found = 0
                proper_format = True

                for i, msg in enumerate(result.conversation_history):
                    if msg.get("role") == "assistant" and msg.get("tool_calls"):
                        tool_calls_found += 1
                        logger.info(
                            f"📝 Message {i}: Found tool calls - {[tc['function']['name'] for tc in msg['tool_calls']]}"
                        )

                        # Validate format
                        for tc in msg["tool_calls"]:
                            if not all(key in tc for key in ["id", "type", "function"]):
                                proper_format = False
                                logger.error(f"❌ Malformed tool call: {tc}")

                logger.info(f"🔧 Total tool calls found: {tool_calls_found}")

                if tool_calls_found > 0 and proper_format:
                    logger.info("✅ SDK + Temporal integration working perfectly!")
                    logger.info("✅ Tool calls properly formatted and processed")
                else:
                    logger.warning("⚠️ Issues with tool call integration")

                # Verify the workflow completed successfully
                assert result.success, "Workflow should complete successfully"
                assert result.reasoning_iterations_used >= 1, "Should use at least one iteration"
                assert tool_calls_found >= 1, "Should make at least one tool call"

                logger.info("🎉 All assertions passed - SDK + Temporal integration verified!")
                logger.info("=" * 60)

            except Exception as e:
                error_msg = str(e)
                logger.error(f"❌ SDK + Temporal integration failed: {error_msg}")

                if "connection" in error_msg.lower() or "11434" in error_msg:
                    pytest.skip("Ollama not available - ensure it's running with qwen2.5 model")
                else:
                    raise

    finally:
        await env.shutdown()


@pytest.mark.asyncio
async def test_sdk_temporal_integration_multiple_tool_calls():
    """Test SDK + Temporal integration with multiple tool calls."""

    logger.info("🧪 Testing SDK + Temporal integration with multiple tool calls")

    # Similar setup but with a more complex task
    dependencies = SDKTemporalTestDependencies()
    activities = make_agent_activities(dependencies)

    from uuid import UUID

    from temporalio import activity

    @activity.defn(name="build_agent_config_activity")
    async def mock_build_agent_config(agent_id: UUID, user_context_data: dict, **kwargs):
        return {
            "id": str(agent_id),
            "name": "Multi-Tool Test Agent",
            "instruction": "You are a helpful assistant. Use tools step by step. First calculate, then complete the task.",
            "model_id": "66666666-6666-6666-6666-666666666666",
            "tools_config": {},
            "events_config": {},
            "planning": False,
        }

    @activity.defn(name="discover_available_tools_activity")
    async def mock_discover_tools(agent_id: UUID, user_context_data: dict, **kwargs):
        return [
            {
                "type": "function",
                "function": {
                    "name": "calculate",
                    "description": "Perform mathematical calculations",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "expression": {"type": "string", "description": "Math expression"}
                        },
                        "required": ["expression"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "task_complete",
                    "description": "Mark task as completed with final result",
                    "parameters": {
                        "type": "object",
                        "properties": {"result": {"type": "string", "description": "Final result"}},
                        "required": ["result"],
                    },
                },
            },
        ]

    @activity.defn(name="call_llm_activity")
    async def sdk_llm_activity(
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
        from agentarea_agents_sdk.models.llm_model import LLMModel, LLMRequest

        model = LLMModel(
            provider_type="ollama_chat", model_name="qwen2.5", endpoint_url="http://localhost:11434"
        )

        request = LLMRequest(messages=messages, tools=tools, temperature=0.1, max_tokens=400)

        response = await model.complete(request)

        logger.info(
            f"🔧 SDK returned {len(response.tool_calls) if response.tool_calls else 0} tool calls"
        )
        if response.tool_calls:
            for tc in response.tool_calls:
                logger.info(f"   Tool: {tc['function']['name']}")

        return {
            "role": response.role,
            "content": response.content,
            "tool_calls": response.tool_calls,
            "cost": response.cost,
            "usage": response.usage.__dict__ if response.usage else None,
        }

    # Replace activities
    real_activities = []
    for activity_func in activities:
        activity_name = getattr(activity_func, "__name__", "")
        if "build_agent_config" in activity_name:
            real_activities.append(mock_build_agent_config)
        elif "discover_available_tools" in activity_name:
            real_activities.append(mock_discover_tools)
        elif "call_llm" in activity_name:
            real_activities.append(sdk_llm_activity)
        else:
            real_activities.append(activity_func)

    execution_request = AgentExecutionRequest(
        agent_id="12345678-1234-5678-1234-567812345678",
        task_id=str(uuid4()),
        user_id="test-user-id",
        task_query="Calculate 12 * 8, then add 5 to the result, and tell me the final answer.",
        task_parameters={
            "success_criteria": ["Perform calculations step by step", "Provide final answer"],
            "max_iterations": 3,
        },
        budget_usd=2.0,
        requires_human_approval=False,
    )

    logger.info(f"📝 Complex task: '{execution_request.task_query}'")

    env = await WorkflowEnvironment.start_time_skipping()
    try:
        async with Worker(
            env.client,
            task_queue="sdk-temporal-multi-test-queue",
            workflows=[AgentExecutionWorkflow],
            activities=real_activities,
            debug_mode=True,
        ):
            try:
                result = await env.client.execute_workflow(
                    AgentExecutionWorkflow.run,
                    execution_request,
                    id=f"sdk-temporal-multi-test-{uuid4()}",
                    task_queue="sdk-temporal-multi-test-queue",
                    execution_timeout=timedelta(minutes=3),
                )

                logger.info("=" * 60)
                logger.info("🎉 MULTI-TOOL SDK + TEMPORAL SUCCESS!")
                logger.info("=" * 60)
                logger.info(f"✅ Success: {result.success}")
                logger.info(f"📊 Iterations: {result.reasoning_iterations_used}")
                logger.info(f"💬 Final response: {result.final_response}")

                # Count different types of tool calls
                calculate_calls = 0
                complete_calls = 0

                for msg in result.conversation_history:
                    if msg.get("tool_calls"):
                        for tc in msg["tool_calls"]:
                            if tc["function"]["name"] == "calculate":
                                calculate_calls += 1
                            elif tc["function"]["name"] == "task_complete":
                                complete_calls += 1

                logger.info(f"🔢 Calculate calls: {calculate_calls}")
                logger.info(f"✅ Complete calls: {complete_calls}")

                # Verify we got the expected tool usage
                assert result.success, "Multi-tool workflow should succeed"
                assert calculate_calls >= 1, "Should make at least one calculation"
                assert complete_calls >= 1, "Should complete the task"

                logger.info("🎉 Multi-tool integration verified successfully!")
                logger.info("=" * 60)

            except Exception as e:
                if "connection" in str(e).lower() or "11434" in str(e):
                    pytest.skip("Ollama not available")
                else:
                    raise

    finally:
        await env.shutdown()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    pytest.main([__file__, "-v", "-s"])
