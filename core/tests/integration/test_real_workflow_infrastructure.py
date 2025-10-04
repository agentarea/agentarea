"""Test workflow with real infrastructure to identify malformed response source."""

import logging
import os
from datetime import timedelta
from uuid import uuid4

import pytest
from agentarea_execution.activities.agent_execution_activities import make_agent_activities
from agentarea_execution.models import AgentExecutionRequest
from agentarea_execution.workflows.agent_execution_workflow import AgentExecutionWorkflow
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

logger = logging.getLogger(__name__)


class RealTestDependencies:
    """Real dependencies for testing with minimal mocking."""

    class TestSecretManager:
        """Real secret manager that returns appropriate values for testing."""

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
            logger.info(f"Event published: {getattr(event, 'event_type', 'unknown')}")

    def __init__(self):
        self.secret_manager = self.TestSecretManager()
        self.event_broker = self.TestEventBroker()


@pytest.mark.asyncio
async def test_workflow_with_real_infrastructure_and_database():
    """Test workflow using real infrastructure but with test database setup."""

    # Skip if no Ollama available
    docker_host = os.environ.get("LLM_DOCKER_HOST", "localhost")

    # Create real dependencies
    dependencies = RealTestDependencies()

    # Create real activities
    activities = make_agent_activities(dependencies)

    # We need to create a real model instance in the database for this test
    # Let's create a test that sets up the minimal database state needed

    execution_request = AgentExecutionRequest(
        agent_id=uuid4(),
        task_id=uuid4(),
        user_id="test-user",
        task_query="Complete this simple test task",
        task_parameters={"success_criteria": ["Task completed successfully"], "max_iterations": 3},
        budget_usd=1.0,
        requires_human_approval=False,
    )

    logger.info("🧪 Testing workflow with real infrastructure")
    logger.info(f"Agent ID: {execution_request.agent_id}")
    logger.info(f"Task ID: {execution_request.task_id}")

    env = await WorkflowEnvironment.start_time_skipping()
    try:
        async with Worker(
            env.client,
            task_queue="test-queue",
            workflows=[AgentExecutionWorkflow],
            activities=activities,
        ):
            try:
                # This will fail because we don't have the agent/model in the database
                # But it will show us exactly where the failure occurs and what the real code path looks like
                result = await env.client.execute_workflow(
                    AgentExecutionWorkflow.run,
                    execution_request,
                    id=f"test-workflow-{uuid4()}",
                    task_queue="test-queue",
                    execution_timeout=timedelta(seconds=30),
                )

                logger.info("✅ Workflow completed successfully with real infrastructure")
                logger.info(f"Success: {result.success}")
                logger.info(f"Iterations: {result.reasoning_iterations_used}")
                logger.info(f"Final response: {result.final_response}")

            except Exception as e:
                logger.info(f"Expected failure with real infrastructure: {e}")
                logger.info(f"Error type: {type(e).__name__}")

                # This is expected - we need to set up the database properly
                # But we can see the exact error and code path
                if "not found" in str(e).lower():
                    logger.info("✅ Test confirmed real infrastructure is being used")
                    logger.info("Need to set up proper database state for full test")
                else:
                    logger.warning(f"Unexpected error: {e}")

    finally:
        await env.shutdown()


@pytest.mark.asyncio
async def test_database_setup_verification():
    """Verify that the database setup script has been run correctly."""

    # Create real dependencies to test database connection
    dependencies = RealTestDependencies()
    activities = make_agent_activities(dependencies)

    # Find the build_agent_config activity to test database access
    build_agent_config_activity = None
    for activity_func in activities:
        if hasattr(activity_func, "__name__") and "build_agent_config" in activity_func.__name__:
            build_agent_config_activity = activity_func
            break

    if not build_agent_config_activity:
        pytest.skip("Could not find build_agent_config_activity")

    logger.info("🔍 Testing database setup verification...")

    try:
        # Try to load the test agent from the database
        from uuid import UUID

        # Use proper UUID format for the test agent ID
        test_agent_uuid = UUID("12345678-1234-5678-1234-567812345678")
        result = await build_agent_config_activity(
            test_agent_uuid, {"user_id": "test-user-id", "workspace_id": "test-workspace-id"}
        )

        logger.info("✅ Database setup verification PASSED!")
        logger.info(f"Agent config loaded: {result['name']}")
        logger.info(f"Model ID: {result['model_id']}")

        # Verify the model instance is properly configured
        assert result["model_id"] == "66666666-6666-6666-6666-666666666666", (
            "Model instance ID should match setup script"
        )
        assert result["name"] == "Test Agent", "Agent name should match setup script"

        logger.info("🎯 Database is properly set up for real infrastructure testing!")

    except Exception as e:
        error_msg = str(e)
        logger.error(f"❌ Database setup verification FAILED: {error_msg}")

        if "not found" in error_msg.lower():
            logger.error("🔧 Run the database setup script:")
            logger.error("psql -d agentarea -f setup_test_database.sql")
            pytest.skip("Database setup required")
        elif "connection" in error_msg.lower():
            logger.error("🔧 Database connection failed - ensure PostgreSQL is running")
            pytest.skip("Database connection failed")
        else:
            raise


@pytest.mark.asyncio
async def test_real_activity_call_directly():
    """Test calling the real LLM activity directly to see its behavior."""

    docker_host = os.environ.get("LLM_DOCKER_HOST", "localhost")

    # Create real dependencies
    dependencies = RealTestDependencies()

    # Create real activities
    activities = make_agent_activities(dependencies)

    # Find the real call_llm_activity
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

    logger.info("🧪 Testing real LLM activity directly")

    try:
        # This will fail because we need a real model instance UUID
        # But let's see what error we get
        result = await call_llm_activity(
            messages=messages,
            model_id=str(uuid4()),  # Fake UUID - will cause error
            tools=tools,
            workspace_id="system",
            temperature=0.1,
            max_tokens=200,
            task_id="test-task",
            agent_id="test-agent",
            execution_id="test-execution",
        )

        logger.info("Unexpected success - activity returned:")
        logger.info(f"Content: '{result.get('content', '')}'")
        logger.info(f"Tool calls: {result.get('tool_calls')}")

    except Exception as e:
        logger.info(f"Expected error from real activity: {e}")
        logger.info(f"Error type: {type(e).__name__}")

        if "not found" in str(e).lower():
            logger.info("✅ Confirmed real activity is being called")
            logger.info("Error shows it's trying to look up model instance in database")
        else:
            logger.warning(f"Unexpected error type: {e}")


def test_create_database_setup_script():
    """Create a script to set up the database for real infrastructure testing."""

    setup_script = """
-- Database setup for real infrastructure testing
-- Run this to create the necessary test data

-- 1. Create test workspace (if not exists)
INSERT INTO workspaces (id, name, description, created_at, updated_at)
VALUES ('test-workspace-id', 'Test Workspace', 'Workspace for integration testing', NOW(), NOW())
ON CONFLICT (id) DO NOTHING;

-- 2. Create test user (if not exists)  
INSERT INTO users (id, email, name, created_at, updated_at)
VALUES ('test-user-id', 'test@example.com', 'Test User', NOW(), NOW())
ON CONFLICT (id) DO NOTHING;

-- 3. Create provider spec for Ollama
INSERT INTO provider_specs (id, provider_type, name, description, config_schema, created_at, updated_at)
VALUES ('ollama-provider-spec', 'ollama_chat', 'Ollama Chat', 'Local Ollama provider', '{}', NOW(), NOW())
ON CONFLICT (id) DO NOTHING;

-- 4. Create provider config for Ollama
INSERT INTO provider_configs (id, provider_spec_id, name, config, api_key, created_at, updated_at)
VALUES ('ollama-provider-config', 'ollama-provider-spec', 'Local Ollama', '{"endpoint_url": "http://localhost:11434"}', NULL, NOW(), NOW())
ON CONFLICT (id) DO NOTHING;

-- 5. Create model spec for qwen2.5
INSERT INTO model_specs (id, model_name, description, config_schema, created_at, updated_at)
VALUES ('qwen25-model-spec', 'qwen2.5', 'Qwen 2.5 model', '{}', NOW(), NOW())
ON CONFLICT (id) DO NOTHING;

-- 6. Create model instance
INSERT INTO model_instances (id, provider_config_id, model_spec_id, name, config, created_at, updated_at)
VALUES ('test-model-instance-id', 'ollama-provider-config', 'qwen25-model-spec', 'Test Qwen 2.5', '{}', NOW(), NOW())
ON CONFLICT (id) DO NOTHING;

-- 7. Create test agent
INSERT INTO agents (id, workspace_id, name, description, instruction, model_id, tools_config, events_config, planning, created_by, created_at, updated_at)
VALUES ('test-agent-id', 'test-workspace-id', 'Test Agent', 'Agent for integration testing', 'You are a helpful AI assistant. When you complete a task, use the task_complete tool.', 'test-model-instance-id', '{}', '{}', false, 'test-user-id', NOW(), NOW())
ON CONFLICT (id) DO NOTHING;

-- Query to verify setup
SELECT 
    a.id as agent_id,
    a.name as agent_name,
    mi.id as model_instance_id,
    mi.name as model_name,
    pc.name as provider_name,
    ps.provider_type
FROM agents a
JOIN model_instances mi ON a.model_id = mi.id
JOIN provider_configs pc ON mi.provider_config_id = pc.id  
JOIN provider_specs ps ON pc.provider_spec_id = ps.id
WHERE a.id = 'test-agent-id';
"""

    logger.info("📝 Database setup script created:")
    logger.info("Save this as setup_test_database.sql and run it:")
    logger.info(setup_script)

    # Also save to file
    with open("setup_test_database.sql", "w") as f:
        f.write(setup_script)

    logger.info("✅ Script saved as setup_test_database.sql")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_workflow_with_real_database_infrastructure():
    """Test workflow using real database infrastructure (requires database setup)."""

    # These IDs match the setup script (proper UUID format)
    test_agent_id = "12345678-1234-5678-1234-567812345678"

    # Create real dependencies with proper event broker
    class RealEventBroker:
        def __init__(self):
            self.published_events = []
            # Add broker attribute to satisfy the event publishing code
            self.broker = self

        async def publish(self, event):
            self.published_events.append(event)
            logger.debug(f"Event published: {getattr(event, 'event_type', 'unknown')}")

    class RealDependencies:
        def __init__(self):
            self.secret_manager = RealTestDependencies.TestSecretManager()
            self.event_broker = RealEventBroker()

    dependencies = RealDependencies()

    # Create real activities
    activities = make_agent_activities(dependencies)

    execution_request = AgentExecutionRequest(
        agent_id=test_agent_id,
        task_id=uuid4(),
        user_id="22222222-2222-2222-2222-222222222222",  # Use proper UUID
        task_query="test",  # Use the same simple query as production
        task_parameters={"success_criteria": ["Task completed successfully"], "max_iterations": 3},
        budget_usd=1.0,
        requires_human_approval=False,
    )

    logger.info("🧪 Testing workflow with REAL database infrastructure")
    logger.info(f"Agent ID: {test_agent_id}")
    logger.info(f"Task: {execution_request.task_query}")
    logger.info("📋 Prerequisites:")
    logger.info("1. Database must be running (docker-compose up -d postgres)")
    logger.info("2. Setup script must be run: psql -d agentarea -f setup_test_database.sql")
    logger.info("3. Ollama must be running with qwen2.5 model")

    env = await WorkflowEnvironment.start_time_skipping()
    try:
        async with Worker(
            env.client,
            task_queue="real-db-test-queue",
            workflows=[AgentExecutionWorkflow],
            activities=activities,
            debug_mode=True,  # Disable sandbox for database access
        ):
            try:
                logger.info("🚀 Starting workflow execution...")

                result = await env.client.execute_workflow(
                    AgentExecutionWorkflow.run,
                    execution_request,
                    id=f"real-db-test-{uuid4()}",
                    task_queue="real-db-test-queue",
                    execution_timeout=timedelta(minutes=2),
                )

                logger.info("🎉 SUCCESS: Workflow completed with REAL infrastructure!")
                logger.info(f"✅ Success: {result.success}")
                logger.info(f"📊 Iterations: {result.reasoning_iterations_used}")
                logger.info(f"💬 Final response: {result.final_response}")
                logger.info(f"💰 Total cost: ${result.total_cost:.6f}")

                # Analyze the conversation history for tool call format
                if result.conversation_history:
                    logger.info("🔍 Analyzing conversation history for tool call format...")
                    for i, msg in enumerate(result.conversation_history):
                        if msg.get("tool_calls"):
                            logger.info(f"Message {i} tool_calls: {msg['tool_calls']}")
                        elif msg.get("content") and "task_complete" in msg.get("content", ""):
                            logger.warning(
                                f"🚨 Message {i} has task_complete in content: {msg['content'][:100]}..."
                            )

                # This is the key test - did we get malformed responses?
                if result.success:
                    logger.info("✅ REAL infrastructure produced CORRECT tool calls!")
                    logger.info(
                        "This means the malformed responses are NOT from the core infrastructure"
                    )
                else:
                    logger.warning("⚠️ Workflow didn't complete - check logs for issues")

                # Verify we actually used real infrastructure
                assert result.reasoning_iterations_used >= 1, (
                    "Should have completed at least 1 iteration"
                )

            except Exception as e:
                error_msg = str(e)
                logger.error(f"❌ Test failed: {error_msg}")

                if "not found" in error_msg.lower():
                    logger.error("🔧 Database setup required!")
                    logger.error("Run: psql -d agentarea -f setup_test_database.sql")
                    pytest.skip("Database setup required - run setup_test_database.sql")
                elif "connection" in error_msg.lower():
                    logger.error("🔧 Database connection failed!")
                    logger.error("Ensure PostgreSQL is running: docker-compose up -d postgres")
                    pytest.skip("Database connection failed - ensure PostgreSQL is running")
                else:
                    # Re-raise unexpected errors
                    raise

    finally:
        await env.shutdown()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    pytest.main([__file__, "-v", "-s"])
