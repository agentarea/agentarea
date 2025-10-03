"""Simple test of real LLM infrastructure with minimal mocking."""

import logging
from datetime import timedelta
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from agentarea_execution.activities.agent_execution_activities import make_agent_activities
from agentarea_execution.models import AgentExecutionRequest
from agentarea_execution.workflows.agent_execution_workflow import AgentExecutionWorkflow
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

logger = logging.getLogger(__name__)


class SimpleMockedDependencies:
    """Dependencies with minimal mocking for LLM testing."""

    class TestSecretManager:
        """Real secret manager for LLM providers."""

        async def get_secret(self, secret_name: str) -> str:
            # For Ollama, return empty string (no API key needed)
            if "ollama" in secret_name.lower():
                return ""
            # For other providers, return a placeholder
            return f"test-api-key-{secret_name}"

    class TestEventBroker:
        """Real event broker that logs events."""

        def __init__(self):
            self.published_events = []
            self.broker = self  # Add broker attribute to avoid errors

        async def publish(self, event):
            self.published_events.append(event)
            logger.debug(f"Event published: {getattr(event, 'event_type', 'unknown')}")

    def __init__(self):
        self.secret_manager = self.TestSecretManager()
        self.event_broker = self.TestEventBroker()


@pytest.mark.asyncio
async def test_real_llm_with_activity_mocking():
    """Test real LLM by mocking only the database lookup activities."""

    logger.info("🧪 Testing REAL LLM with activity-level mocking")
    logger.info("🎯 This tests the actual LLM call infrastructure")

    # Create dependencies
    dependencies = SimpleMockedDependencies()

    # Create real activities
    activities = make_agent_activities(dependencies)

    # Mock only the build_agent_config activity to return test data
    async def mock_build_agent_config(agent_id: str, context: dict):
        logger.info(f"Mock: Building agent config for {agent_id}")
        return {
            "id": agent_id,
            "name": "Test Agent",
            "instruction": "You are a helpful AI assistant. When you complete a task, use the task_complete tool to mark it as completed.",
            "model_id": "66666666-6666-6666-6666-666666666666",
            "tools_config": {},
            "events_config": {},
            "planning": False,
        }

    # Mock the discover_tools activity
    async def mock_discover_tools(agent_id: str, context: dict):
        logger.info(f"Mock: Discovering tools for {agent_id}")
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

    # Mock the call_llm activity to use real LLM but with mocked model lookup
    original_call_llm = None
    for i, activity_func in enumerate(activities):
        if hasattr(activity_func, "__name__"):
            if "build_agent_config" in activity_func.__name__:
                activities[i] = mock_build_agent_config
            elif "discover_tools" in activity_func.__name__:
                activities[i] = mock_discover_tools
            elif "call_llm" in activity_func.__name__:
                original_call_llm = activity_func

    if not original_call_llm:
        pytest.skip("Could not find call_llm activity")

    # Create a wrapper for the LLM activity that mocks the model lookup
    async def mock_call_llm_with_real_inference(
        messages,
        model_id,
        tools,
        workspace_id,
        temperature=0.1,
        max_tokens=500,
        task_id=None,
        agent_id=None,
        execution_id=None,
    ):
        logger.info("🚀 Real LLM call with mocked model lookup")
        logger.info(f"📝 Messages: {len(messages)} messages")
        logger.info(f"🔧 Tools: {len(tools)} tools")
        logger.info(f"🎯 Model ID: {model_id} (will use real Ollama)")

        # Mock the model instance lookup to return Ollama configuration
        with patch(
            "agentarea_llm.infrastructure.model_instance_repository.ModelInstanceRepository"
        ) as mock_repo:
            mock_instance = mock_repo.return_value
            mock_instance.get_model_with_provider = AsyncMock(
                return_value={
                    "id": model_id,
                    "name": "Test Qwen 2.5",
                    "config": {},
                    "provider_config": {
                        "id": "ollama-provider-config",
                        "name": "Local Ollama",
                        "config": {"endpoint_url": "http://localhost:11434"},
                        "api_key": None,
                    },
                    "provider_spec": {
                        "id": "ollama-provider-spec",
                        "provider_type": "ollama_chat",
                        "name": "Ollama Chat",
                    },
                    "model_spec": {
                        "id": "qwen25-model-spec",
                        "model_name": "qwen2.5",
                        "description": "Qwen 2.5 model",
                    },
                }
            )

            logger.info("📡 Starting real LLM call...")

            # Call the real LLM activity
            result = await original_call_llm(
                messages=messages,
                model_id=model_id,
                tools=tools,
                workspace_id=workspace_id,
                temperature=temperature,
                max_tokens=max_tokens,
                task_id=task_id,
                agent_id=agent_id,
                execution_id=execution_id,
            )

            logger.info("✅ Real LLM call completed")

            # Analyze the result
            content = result.get("content", "")
            tool_calls = result.get("tool_calls", [])
            cost = result.get("cost", 0)

            logger.info("=" * 60)
            logger.info("🎯 REAL LLM RESPONSE ANALYSIS")
            logger.info("=" * 60)
            logger.info(f"📝 Content length: {len(content)} chars")
            logger.info(f"🔧 Tool calls: {tool_calls}")
            logger.info(f"💰 Cost: ${cost}")

            if tool_calls:
                logger.info("✅ Response format is CORRECT - tool calls properly returned")
                for i, tc in enumerate(tool_calls):
                    logger.info(f"   Tool {i}: {tc.get('function', {}).get('name', 'unknown')}")
            elif content and ("task_complete" in content or '"function"' in content):
                logger.warning("🚨 Response format is MALFORMED - tool calls in content")
                logger.warning(f"Content preview: {content[:200]}...")
            else:
                logger.info("📄 Response is regular content (no tool calls expected)")

            logger.info("=" * 60)

            return result

    # Replace the call_llm activity
    for i, activity_func in enumerate(activities):
        if hasattr(activity_func, "__name__") and "call_llm" in activity_func.__name__:
            activities[i] = mock_call_llm_with_real_inference
            break

    # Test execution request
    execution_request = AgentExecutionRequest(
        agent_id="12345678-1234-5678-1234-567812345678",
        task_id=str(uuid4()),
        user_id="test-user-id",
        task_query="test",  # Simple task like production
        task_parameters={"success_criteria": ["Task completed successfully"], "max_iterations": 3},
        budget_usd=1.0,
        requires_human_approval=False,
    )

    logger.info(f"🤖 Agent ID: {execution_request.agent_id}")
    logger.info(f"📝 Task: '{execution_request.task_query}'")
    logger.info(f"💰 Budget: ${execution_request.budget_usd}")
    logger.info(f"🔄 Max iterations: {execution_request.task_parameters['max_iterations']}")

    env = await WorkflowEnvironment.start_time_skipping()
    try:
        async with Worker(
            env.client,
            task_queue="simple-llm-test-queue",
            workflows=[AgentExecutionWorkflow],
            activities=activities,
            debug_mode=True,  # Allow real network calls
        ):
            logger.info("🚀 Starting workflow execution...")

            try:
                result = await env.client.execute_workflow(
                    AgentExecutionWorkflow.run,
                    execution_request,
                    id=f"simple-llm-test-{uuid4()}",
                    task_queue="simple-llm-test-queue",
                    execution_timeout=timedelta(minutes=2),
                )

                logger.info("=" * 60)
                logger.info("🎉 WORKFLOW EXECUTION COMPLETED!")
                logger.info("=" * 60)
                logger.info(f"✅ Success: {result.success}")
                logger.info(f"📊 Iterations: {result.reasoning_iterations_used}")
                logger.info(f"💬 Final response: {result.final_response}")
                logger.info(f"💰 Total cost: ${result.total_cost:.6f}")
                logger.info(f"📝 Conversation messages: {len(result.conversation_history)}")

                # Detailed analysis of conversation history
                logger.info("\n🔍 CONVERSATION ANALYSIS:")
                malformed_responses = 0
                proper_tool_calls = 0

                for i, msg in enumerate(result.conversation_history):
                    role = msg.get("role", "unknown")
                    content = msg.get("content", "")
                    tool_calls = msg.get("tool_calls", [])

                    if role == "assistant":
                        content_len = len(content) if content else 0
                        has_tool_calls = bool(tool_calls)

                        logger.info(
                            f"📝 Message {i} ({role}): {content_len} chars, tool_calls: {has_tool_calls}"
                        )

                        if has_tool_calls:
                            proper_tool_calls += 1
                            logger.info(f"✅ Message {i}: Proper tool calls detected")
                        elif content and (
                            "task_complete" in content or "function" in content.lower()
                        ):
                            malformed_responses += 1
                            logger.warning(f"🚨 Message {i}: Potential malformed response detected")
                            logger.warning(f"   Content preview: {content[:200]}...")

                logger.info("\n" + "=" * 60)
                logger.info("🎯 FINAL ASSESSMENT")
                logger.info("=" * 60)
                logger.info(f"✅ Proper tool calls: {proper_tool_calls}")
                logger.info(f"🚨 Malformed responses: {malformed_responses}")

                if malformed_responses == 0:
                    logger.info("✅ NO MALFORMED RESPONSES DETECTED!")
                    logger.info("The real LLM infrastructure works correctly")
                    logger.info("Production malformed responses must be from:")
                    logger.info("- Different model/provider configuration")
                    logger.info("- Different environment setup")
                    logger.info("- Database configuration issues")
                else:
                    logger.warning(f"⚠️ FOUND {malformed_responses} MALFORMED RESPONSES!")
                    logger.warning("The issue is in the LLM infrastructure itself")

                logger.info("🎉 Workflow completed successfully with real LLM!")
                logger.info("=" * 60)

            except Exception as e:
                error_msg = str(e)
                logger.error(f"❌ Workflow execution failed: {error_msg}")

                if "connection" in error_msg.lower() or "11434" in error_msg:
                    logger.error("🔧 Ollama connection failed!")
                    logger.error("Ensure Ollama is running: ollama serve")
                    logger.error("And qwen2.5 model is available: ollama pull qwen2.5")
                    pytest.skip("Ollama not available - ensure it's running with qwen2.5 model")
                else:
                    # Re-raise unexpected errors for debugging
                    raise

    finally:
        await env.shutdown()


@pytest.mark.asyncio
async def test_direct_real_llm_call():
    """Test direct real LLM call with minimal setup."""

    logger.info("🧪 Testing direct real LLM call")

    # Create dependencies
    dependencies = SimpleMockedDependencies()

    # Create real activities
    activities = make_agent_activities(dependencies)

    # Find the call_llm activity
    call_llm_activity = None
    for activity_func in activities:
        if hasattr(activity_func, "__name__") and "call_llm" in activity_func.__name__:
            call_llm_activity = activity_func
            break

    if not call_llm_activity:
        pytest.skip("Could not find call_llm_activity")

    # Test messages that match production
    messages = [
        {
            "role": "system",
            "content": "You are a helpful AI assistant. When you complete a task, use the task_complete tool to mark it as completed.",
        },
        {
            "role": "user",
            "content": "test",  # Same simple query as production
        },
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

    logger.info("🚀 Making direct real LLM call...")
    logger.info(f"📝 Messages: {len(messages)} messages")
    logger.info(f"🔧 Tools: {len(tools)} tools")

    # Mock the model instance lookup
    with patch(
        "agentarea_llm.infrastructure.model_instance_repository.ModelInstanceRepository"
    ) as mock_repo:
        mock_instance = mock_repo.return_value
        mock_instance.get_model_with_provider = AsyncMock(
            return_value={
                "id": "66666666-6666-6666-6666-666666666666",
                "name": "Test Qwen 2.5",
                "config": {},
                "provider_config": {
                    "id": "ollama-provider-config",
                    "name": "Local Ollama",
                    "config": {"endpoint_url": "http://localhost:11434"},
                    "api_key": None,
                },
                "provider_spec": {
                    "id": "ollama-provider-spec",
                    "provider_type": "ollama_chat",
                    "name": "Ollama Chat",
                },
                "model_spec": {
                    "id": "qwen25-model-spec",
                    "model_name": "qwen2.5",
                    "description": "Qwen 2.5 model",
                },
            }
        )

        try:
            result = await call_llm_activity(
                messages=messages,
                model_id="66666666-6666-6666-6666-666666666666",  # Use proper UUID format
                tools=tools,
                workspace_id="test-workspace-id",
                temperature=0.1,
                max_tokens=500,
                task_id="test-task",
                agent_id="test-agent",
                execution_id="test-execution",
            )

            logger.info("=" * 60)
            logger.info("🎯 DIRECT REAL LLM CALL RESULT")
            logger.info("=" * 60)

            content = result.get("content", "")
            tool_calls = result.get("tool_calls", [])
            cost = result.get("cost", 0)

            logger.info(f"📝 Content length: {len(content)} chars")
            logger.info(f"🔧 Tool calls: {tool_calls}")
            logger.info(f"💰 Cost: ${cost}")

            if content:
                logger.info(f"📄 Content preview: {content[:300]}...")

            # Analyze response format
            if tool_calls:
                logger.info("✅ Response format is CORRECT - tool calls properly returned")
                for i, tc in enumerate(tool_calls):
                    logger.info(f"   Tool {i}: {tc.get('function', {}).get('name', 'unknown')}")
                    logger.info(f"   Args: {tc.get('function', {}).get('arguments', 'none')}")
            elif content and ("task_complete" in content or '"function"' in content):
                logger.warning("🚨 Response format is MALFORMED - tool calls in content")
                logger.warning("This indicates the LLM is not properly formatting tool calls")
            else:
                logger.info("📄 Response is regular content (no tool calls)")

            logger.info("=" * 60)

        except Exception as e:
            error_msg = str(e)
            logger.error(f"❌ Direct LLM call failed: {error_msg}")

            if "connection" in error_msg.lower() or "11434" in error_msg:
                logger.error("🔧 Ollama connection failed!")
                pytest.skip("Ollama not available")
            else:
                raise


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    pytest.main([__file__, "-v", "-s"])
