"""Test real LLM infrastructure with mocked database to isolate malformed response source."""

import logging
import os
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from agentarea_execution.activities.agent_execution_activities import make_agent_activities
from agentarea_execution.models import AgentExecutionRequest
from agentarea_execution.workflows.agent_execution_workflow import AgentExecutionWorkflow
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

logger = logging.getLogger(__name__)


class MockedDatabaseDependencies:
    """Dependencies with mocked database but real LLM infrastructure."""

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


@pytest.fixture
def mock_database_calls():
    """Mock all database calls to return test data."""

    # Test agent configuration
    test_agent_config = {
        "id": "12345678-1234-5678-1234-567812345678",
        "name": "Test Agent",
        "description": "Test agent for malformed response debugging",
        "instruction": "You are a helpful AI assistant. When you complete a task, use the task_complete tool to mark it as completed.",
        "model_id": "66666666-6666-6666-6666-666666666666",
        "tools_config": {},
        "events_config": {},
        "planning": False,
        "workspace_id": "test-workspace-id",
        "created_by": "test-user-id",
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }

    # Test model instance configuration
    test_model_instance = {
        "id": "66666666-6666-6666-6666-666666666666",
        "name": "Test Qwen 2.5",
        "provider_config_id": "ollama-provider-config",
        "model_spec_id": "qwen25-model-spec",
        "config": {},
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }

    # Test provider configuration
    test_provider_config = {
        "id": "ollama-provider-config",
        "name": "Local Ollama",
        "provider_spec_id": "ollama-provider-spec",
        "config": {"endpoint_url": "http://localhost:11434"},
        "api_key": None,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }

    # Test provider spec
    test_provider_spec = {
        "id": "ollama-provider-spec",
        "provider_type": "ollama_chat",
        "name": "Ollama Chat",
        "description": "Local Ollama provider",
        "config_schema": {},
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }

    # Test model spec
    test_model_spec = {
        "id": "qwen25-model-spec",
        "model_name": "qwen2.5",
        "description": "Qwen 2.5 model",
        "config_schema": {},
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }

    # Mock the database repositories
    with (
        patch("agentarea_agents.infrastructure.repository.AgentRepository") as mock_agent_repo,
        patch(
            "agentarea_llm.infrastructure.model_instance_repository.ModelInstanceRepository"
        ) as mock_model_repo,
        patch(
            "agentarea_llm.infrastructure.provider_config_repository.ProviderConfigRepository"
        ) as mock_provider_repo,
        patch(
            "agentarea_llm.infrastructure.provider_spec_repository.ProviderSpecRepository"
        ) as mock_spec_repo,
        patch("agentarea_tasks.infrastructure.repository.TaskRepository") as mock_task_repo,
    ):
        # Configure agent repository
        mock_agent_instance = mock_agent_repo.return_value
        mock_agent_instance.get_by_id = AsyncMock(return_value=test_agent_config)
        mock_agent_instance.get_agent_with_model = AsyncMock(
            return_value={
                **test_agent_config,
                "model_instance": test_model_instance,
                "provider_config": test_provider_config,
                "provider_spec": test_provider_spec,
                "model_spec": test_model_spec,
            }
        )

        # Configure model repository
        mock_model_instance = mock_model_repo.return_value
        mock_model_instance.get_by_id = AsyncMock(return_value=test_model_instance)
        mock_model_instance.get_model_with_provider = AsyncMock(
            return_value={
                **test_model_instance,
                "provider_config": test_provider_config,
                "provider_spec": test_provider_spec,
                "model_spec": test_model_spec,
            }
        )

        # Configure provider repository
        mock_provider_instance = mock_provider_repo.return_value
        mock_provider_instance.get_by_id = AsyncMock(return_value=test_provider_config)
        mock_provider_instance.get_provider_with_spec = AsyncMock(
            return_value={**test_provider_config, "provider_spec": test_provider_spec}
        )

        # Configure spec repository
        mock_spec_instance = mock_spec_repo.return_value
        mock_spec_instance.get_by_id = AsyncMock(return_value=test_provider_spec)

        # Configure task repository
        mock_task_instance = mock_task_repo.return_value
        mock_task_instance.create = AsyncMock(return_value={"id": str(uuid4())})
        mock_task_instance.update = AsyncMock()
        mock_task_instance.get_by_id = AsyncMock(
            return_value={"id": str(uuid4()), "status": "pending", "created_at": datetime.now(UTC)}
        )

        yield {
            "agent_repo": mock_agent_instance,
            "model_repo": mock_model_instance,
            "provider_repo": mock_provider_instance,
            "spec_repo": mock_spec_instance,
            "task_repo": mock_task_instance,
        }


@pytest.mark.asyncio
async def test_real_llm_with_mocked_database(mock_database_calls):
    """Test real LLM infrastructure with mocked database to isolate response format issues."""

    # Skip if no Ollama available
    docker_host = os.environ.get("LLM_DOCKER_HOST", "localhost")

    logger.info("🧪 Testing REAL LLM with MOCKED database")
    logger.info("🎯 This isolates LLM response format issues from database problems")
    logger.info(f"🔗 Using Ollama at: {docker_host}:11434")

    # Create dependencies with mocked database
    dependencies = MockedDatabaseDependencies()

    # Create real activities (but database calls will be mocked)
    activities = make_agent_activities(dependencies)

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
            task_queue="real-llm-test-queue",
            workflows=[AgentExecutionWorkflow],
            activities=activities,
            debug_mode=True,  # Allow real network calls
        ):
            logger.info("🚀 Starting workflow execution...")

            try:
                result = await env.client.execute_workflow(
                    AgentExecutionWorkflow.run,
                    execution_request,
                    id=f"real-llm-test-{uuid4()}",
                    task_queue="real-llm-test-queue",
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
                            for tc in tool_calls:
                                logger.info(
                                    f"   🔧 Tool: {tc.get('function', {}).get('name', 'unknown')}"
                                )
                        elif content and (
                            "task_complete" in content or "function" in content.lower()
                        ):
                            malformed_responses += 1
                            logger.warning(f"🚨 Message {i}: Potential malformed response detected")
                            logger.warning(f"   Content preview: {content[:200]}...")
                        else:
                            logger.info(f"📄 Message {i}: Regular content message")

                logger.info("\n" + "=" * 60)
                logger.info("🎯 FINAL ASSESSMENT")
                logger.info("=" * 60)
                logger.info(f"✅ Proper tool calls: {proper_tool_calls}")
                logger.info(f"🚨 Malformed responses: {malformed_responses}")

                if malformed_responses == 0:
                    logger.info("✅ NO MALFORMED RESPONSES DETECTED!")
                    logger.info("The real LLM infrastructure works correctly with mocked database")
                    logger.info("Production malformed responses must be from:")
                    logger.info("- Different model/provider configuration")
                    logger.info("- Different environment setup")
                    logger.info("- Database configuration issues")
                    logger.info("- Network/connectivity problems")
                else:
                    logger.warning(f"⚠️ FOUND {malformed_responses} MALFORMED RESPONSES!")
                    logger.warning("The issue is in the LLM infrastructure itself")
                    logger.warning("Check:")
                    logger.warning("- Model configuration")
                    logger.warning("- LiteLLM setup")
                    logger.warning("- Ollama model version")
                    logger.warning("- Tool definition format")

                # Verify we actually completed successfully
                if result.success:
                    logger.info("🎉 Workflow completed successfully with real LLM!")
                    assert result.reasoning_iterations_used >= 1, (
                        "Should have completed at least 1 iteration"
                    )
                else:
                    logger.warning("⚠️ Workflow didn't complete successfully - check logs")

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
async def test_direct_llm_call_with_mocked_db(mock_database_calls):
    """Test direct LLM call with mocked database to see raw response format."""

    logger.info("🧪 Testing direct LLM call with mocked database")

    # Create dependencies with mocked database
    dependencies = MockedDatabaseDependencies()

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

    logger.info("🚀 Making direct LLM call...")
    logger.info(f"📝 Messages: {len(messages)} messages")
    logger.info(f"🔧 Tools: {len(tools)} tools")
    logger.info("🎯 Model ID: 66666666-6666-6666-6666-666666666666 (mocked)")

    try:
        result = await call_llm_activity(
            messages=messages,
            model_id="66666666-6666-6666-6666-666666666666",  # This will be mocked
            tools=tools,
            workspace_id="test-workspace-id",
            temperature=0.1,
            max_tokens=500,
            task_id="test-task",
            agent_id="12345678-1234-5678-1234-567812345678",
            execution_id="test-execution",
        )

        logger.info("=" * 60)
        logger.info("🎯 DIRECT LLM CALL RESULT")
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
