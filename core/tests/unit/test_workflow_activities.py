"""Unit tests for workflow activities."""

import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from agentarea_common.events.broker import EventBroker
from agentarea_common.infrastructure.secret_manager import BaseSecretManager
from agentarea_execution.activities.agent_execution_activities import make_agent_activities
from agentarea_execution.interfaces import ActivityDependencies


@pytest.fixture
def mock_event_broker():
    """Mock event broker."""
    broker = MagicMock(spec=EventBroker)
    broker.broker = MagicMock()  # Add broker attribute for RedisRouter compatibility
    return broker


@pytest.fixture
def mock_secret_manager():
    """Mock secret manager."""
    manager = MagicMock(spec=BaseSecretManager)
    return manager


@pytest.fixture
def activity_dependencies(mock_event_broker, mock_secret_manager):
    """Create activity dependencies."""
    return ActivityDependencies(event_broker=mock_event_broker, secret_manager=mock_secret_manager)


@pytest.fixture
def workflow_activities(activity_dependencies):
    """Create workflow activities with mocked dependencies."""
    return make_agent_activities(activity_dependencies)


class TestPublishWorkflowEventsActivity:
    """Test cases for publish_workflow_events_activity."""

    @pytest.mark.asyncio
    async def test_publish_workflow_events_success(self, workflow_activities, mock_event_broker):
        """Test successful workflow event publishing."""
        # Get the publish activity
        publish_activity = None
        for activity in workflow_activities:
            if activity.__name__ == "publish_workflow_events_activity":
                publish_activity = activity
                break

        assert publish_activity is not None, "publish_workflow_events_activity not found"

        # Setup test data
        task_id = str(uuid4())
        events_json = [
            json.dumps(
                {
                    "event_id": str(uuid4()),
                    "event_type": "LLMCallStarted",
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "data": {"task_id": task_id, "agent_id": str(uuid4()), "model": "gpt-4"},
                }
            ),
            json.dumps(
                {
                    "event_id": str(uuid4()),
                    "event_type": "LLMCallCompleted",
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "data": {"task_id": task_id, "agent_id": str(uuid4()), "tokens": 150},
                }
            ),
        ]

        # Mock the dependencies
        with (
            patch(
                "agentarea_execution.activities.agent_execution_activities.create_event_broker_from_router"
            ) as mock_create_broker,
            patch(
                "agentarea_execution.activities.agent_execution_activities.get_database"
            ) as mock_get_db,
            patch(
                "agentarea_execution.activities.agent_execution_activities.TaskEventService"
            ) as mock_service_class,
        ):
            # Setup mocks
            mock_redis_broker = AsyncMock()
            mock_create_broker.return_value = mock_redis_broker

            mock_database = MagicMock()
            mock_session = AsyncMock()
            mock_database.async_session_factory.return_value.__aenter__.return_value = mock_session
            mock_get_db.return_value = mock_database

            mock_service = AsyncMock()
            mock_service_class.return_value = mock_service

            # Execute
            result = await publish_activity(events_json)

            # Verify
            assert result is True

            # Verify Redis event publishing
            assert mock_redis_broker.publish.call_count == 2

            # Verify database persistence via service
            assert mock_service.create_workflow_event.call_count == 2

            # Verify session commit
            mock_session.commit.assert_called()

    @pytest.mark.asyncio
    async def test_publish_workflow_events_empty_list(self, workflow_activities):
        """Test publishing empty event list."""
        # Get the publish activity
        publish_activity = None
        for activity in workflow_activities:
            if activity.__name__ == "publish_workflow_events_activity":
                publish_activity = activity
                break

        # Execute with empty list
        result = await publish_activity([])

        # Verify
        assert result is True

    @pytest.mark.asyncio
    async def test_publish_workflow_events_invalid_json(
        self, workflow_activities, mock_event_broker
    ):
        """Test handling of invalid JSON in events."""
        # Get the publish activity
        publish_activity = None
        for activity in workflow_activities:
            if activity.__name__ == "publish_workflow_events_activity":
                publish_activity = activity
                break

        # Setup test data with invalid JSON
        events_json = [
            "invalid json string",
            json.dumps(
                {
                    "event_type": "ValidEvent",
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "data": {"task_id": str(uuid4())},
                }
            ),
        ]

        # Mock the dependencies
        with (
            patch(
                "agentarea_execution.activities.agent_execution_activities.create_event_broker_from_router"
            ) as mock_create_broker,
            patch(
                "agentarea_execution.activities.agent_execution_activities.get_database"
            ) as mock_get_db,
            patch(
                "agentarea_execution.activities.agent_execution_activities.TaskEventService"
            ) as mock_service_class,
        ):
            # Setup mocks
            mock_redis_broker = AsyncMock()
            mock_create_broker.return_value = mock_redis_broker

            mock_database = MagicMock()
            mock_session = AsyncMock()
            mock_database.async_session_factory.return_value.__aenter__.return_value = mock_session
            mock_get_db.return_value = mock_database

            mock_service = AsyncMock()
            mock_service_class.return_value = mock_service

            # Execute - should handle invalid JSON gracefully
            result = await publish_activity(events_json)

            # Verify - should return False due to JSON parsing error
            assert result is False

    @pytest.mark.asyncio
    async def test_publish_workflow_events_database_error(
        self, workflow_activities, mock_event_broker
    ):
        """Test handling of database errors during event persistence."""
        # Get the publish activity
        publish_activity = None
        for activity in workflow_activities:
            if activity.__name__ == "publish_workflow_events_activity":
                publish_activity = activity
                break

        # Setup test data
        task_id = str(uuid4())
        events_json = [
            json.dumps(
                {
                    "event_id": str(uuid4()),
                    "event_type": "LLMCallStarted",
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "data": {"task_id": task_id, "agent_id": str(uuid4()), "model": "gpt-4"},
                }
            )
        ]

        # Mock the dependencies
        with (
            patch(
                "agentarea_execution.activities.agent_execution_activities.create_event_broker_from_router"
            ) as mock_create_broker,
            patch(
                "agentarea_execution.activities.agent_execution_activities.get_database"
            ) as mock_get_db,
            patch(
                "agentarea_execution.activities.agent_execution_activities.TaskEventService"
            ) as mock_service_class,
        ):
            # Setup mocks
            mock_redis_broker = AsyncMock()
            mock_create_broker.return_value = mock_redis_broker

            mock_database = MagicMock()
            mock_session = AsyncMock()
            mock_database.async_session_factory.return_value.__aenter__.return_value = mock_session
            mock_get_db.return_value = mock_database

            mock_service = AsyncMock()
            mock_service.create_workflow_event.side_effect = Exception("Database connection failed")
            mock_service_class.return_value = mock_service

            # Execute - should handle database errors gracefully
            result = await publish_activity(events_json)

            # Verify - should still return True (Redis publishing succeeded)
            # Database errors are logged but don't fail the activity
            assert result is True

            # Verify Redis publishing still happened
            mock_redis_broker.publish.assert_called_once()

    @pytest.mark.asyncio
    async def test_publish_workflow_events_redis_error(
        self, workflow_activities, mock_event_broker
    ):
        """Test handling of Redis publishing errors."""
        # Get the publish activity
        publish_activity = None
        for activity in workflow_activities:
            if activity.__name__ == "publish_workflow_events_activity":
                publish_activity = activity
                break

        # Setup test data
        task_id = str(uuid4())
        events_json = [
            json.dumps(
                {
                    "event_id": str(uuid4()),
                    "event_type": "LLMCallStarted",
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "data": {"task_id": task_id, "agent_id": str(uuid4()), "model": "gpt-4"},
                }
            )
        ]

        # Mock the dependencies
        with patch(
            "agentarea_execution.activities.agent_execution_activities.create_event_broker_from_router"
        ) as mock_create_broker:
            # Setup mocks - Redis broker fails
            mock_redis_broker = AsyncMock()
            mock_redis_broker.publish.side_effect = Exception("Redis connection failed")
            mock_create_broker.return_value = mock_redis_broker

            # Execute - should handle Redis errors gracefully
            result = await publish_activity(events_json)

            # Verify - should return False due to Redis error
            assert result is False


class TestCallLLMActivity:
    """Test cases for call_llm_activity."""

    @pytest.mark.asyncio
    async def test_call_llm_activity_success(self, workflow_activities):
        """Test successful LLM call activity."""
        # Get the call_llm activity
        call_llm_activity = None
        for activity in workflow_activities:
            if activity.__name__ == "call_llm_activity":
                call_llm_activity = activity
                break

        assert call_llm_activity is not None, "call_llm_activity not found"

        # Setup test data
        messages = [{"role": "user", "content": "Hello"}]
        model_id = str(uuid4())
        workspace_id = "test-workspace"

        # Mock the dependencies
        with (
            patch(
                "agentarea_execution.activities.agent_execution_activities.get_database"
            ) as mock_get_db,
            patch(
                "agentarea_execution.activities.agent_execution_activities.ModelInstanceService"
            ) as mock_service_class,
            patch(
                "agentarea_execution.activities.agent_execution_activities.LLMModel"
            ) as mock_llm_class,
        ):
            # Setup database mock
            mock_database = MagicMock()
            mock_session = AsyncMock()
            mock_database.async_session_factory.return_value.__aenter__.return_value = mock_session
            mock_get_db.return_value = mock_database

            # Setup model instance service mock
            mock_service = AsyncMock()
            mock_model_instance = MagicMock()
            mock_model_instance.provider_config.provider_spec.provider_type = "openai"
            mock_model_instance.model_spec.model_name = "gpt-4"
            mock_model_instance.provider_config.api_key = "test-api-key"
            mock_service.get.return_value = mock_model_instance
            mock_service_class.return_value = mock_service

            # Setup LLM model mock
            mock_llm = AsyncMock()
            mock_response = MagicMock()
            mock_response.content = "Hello! How can I help you?"
            mock_response.role = "assistant"
            mock_response.cost = 0.001
            mock_response.usage.prompt_tokens = 10
            mock_response.usage.completion_tokens = 15
            mock_response.usage.total_tokens = 25
            mock_response.tool_calls = None
            mock_llm.complete.return_value = mock_response
            mock_llm_class.return_value = mock_llm

            # Execute
            result = await call_llm_activity(
                messages=messages, model_id=model_id, workspace_id=workspace_id
            )

            # Verify
            assert result["content"] == "Hello! How can I help you?"
            assert result["role"] == "assistant"
            assert result["cost"] == 0.001
            assert result["usage"]["prompt_tokens"] == 10
            assert result["usage"]["completion_tokens"] == 15
            assert result["usage"]["total_tokens"] == 25

    @pytest.mark.asyncio
    async def test_call_llm_activity_invalid_model_id(self, workflow_activities):
        """Test LLM call activity with invalid model ID."""
        # Get the call_llm activity
        call_llm_activity = None
        for activity in workflow_activities:
            if activity.__name__ == "call_llm_activity":
                call_llm_activity = activity
                break

        # Setup test data with invalid UUID
        messages = [{"role": "user", "content": "Hello"}]
        model_id = "invalid-uuid"
        workspace_id = "test-workspace"

        # Execute & Verify
        with pytest.raises(ValueError, match="Invalid model_id"):
            await call_llm_activity(messages=messages, model_id=model_id, workspace_id=workspace_id)

    @pytest.mark.asyncio
    async def test_call_llm_activity_model_not_found(self, workflow_activities):
        """Test LLM call activity when model instance is not found."""
        # Get the call_llm activity
        call_llm_activity = None
        for activity in workflow_activities:
            if activity.__name__ == "call_llm_activity":
                call_llm_activity = activity
                break

        # Setup test data
        messages = [{"role": "user", "content": "Hello"}]
        model_id = str(uuid4())
        workspace_id = "test-workspace"

        # Mock the dependencies
        with (
            patch(
                "agentarea_execution.activities.agent_execution_activities.get_database"
            ) as mock_get_db,
            patch(
                "agentarea_execution.activities.agent_execution_activities.ModelInstanceService"
            ) as mock_service_class,
        ):
            # Setup database mock
            mock_database = MagicMock()
            mock_session = AsyncMock()
            mock_database.async_session_factory.return_value.__aenter__.return_value = mock_session
            mock_get_db.return_value = mock_database

            # Setup model instance service mock - model not found
            mock_service = AsyncMock()
            mock_service.get.return_value = None
            mock_service_class.return_value = mock_service

            # Execute & Verify
            with pytest.raises(ValueError, match="Model instance.*not found"):
                await call_llm_activity(
                    messages=messages, model_id=model_id, workspace_id=workspace_id
                )
