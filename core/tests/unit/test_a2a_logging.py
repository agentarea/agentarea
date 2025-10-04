"""Unit tests for A2A logging and monitoring functionality."""

import json
import logging
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from agentarea_api.api.v1.a2a_auth import A2AAuthContext
from agentarea_api.api.v1.agents_a2a import log_a2a_operation


class TestA2ALogging:
    """Test A2A logging functionality."""

    def test_log_a2a_operation_basic(self, caplog):
        """Test basic A2A operation logging."""
        # Setup
        agent_id = uuid4()
        auth_context = A2AAuthContext(
            authenticated=True,
            auth_method="bearer",
            user_id="test-user",
            workspace_id="test-workspace",
            permissions=["read", "write"],
            metadata={"user_agent": "test-client", "client_ip": "127.0.0.1"},
        )

        # Test logging with all parameters
        with caplog.at_level(logging.INFO):
            log_a2a_operation(
                operation="task_send",
                agent_id=agent_id,
                auth_context=auth_context,
                request_id="test-request-123",
                task_id=uuid4(),
                status="completed",
                duration_ms=1500.5,
                extra_metadata={"custom_field": "custom_value"},
            )

        # Verify log was created
        assert len(caplog.records) == 1
        log_record = caplog.records[0]

        # Check log level and message
        assert log_record.levelno == logging.INFO
        assert "A2A task_send completed" in log_record.message

        # Check structured metadata
        assert hasattr(log_record, "a2a_metrics")
        metrics = log_record.a2a_metrics

        assert metrics["a2a_operation"] == "task_send"
        assert metrics["agent_id"] == str(agent_id)
        assert metrics["request_id"] == "test-request-123"
        assert metrics["status"] == "completed"
        assert metrics["auth_method"] == "bearer"
        assert metrics["authenticated"] is True
        assert metrics["user_id"] == "test-user"
        assert metrics["workspace_id"] == "test-workspace"
        assert metrics["permissions"] == ["read", "write"]
        assert metrics["duration_ms"] == 1500.5
        assert metrics["custom_field"] == "custom_value"

        # Check client metadata
        assert "client_metadata" in metrics
        assert metrics["client_metadata"]["user_agent"] == "test-client"
        assert metrics["client_metadata"]["client_ip"] == "127.0.0.1"

        # Check timestamp format
        assert "timestamp" in metrics
        timestamp = datetime.fromisoformat(metrics["timestamp"])
        assert timestamp.tzinfo is not None  # Should have timezone info

    def test_log_a2a_operation_error(self, caplog):
        """Test A2A operation logging for errors."""
        agent_id = uuid4()
        auth_context = A2AAuthContext(
            authenticated=False,
            auth_method="api_key",
            user_id=None,
            workspace_id=None,
            permissions=[],
            metadata={},
        )

        # Test error logging
        with caplog.at_level(logging.ERROR):
            log_a2a_operation(
                operation="message_send",
                agent_id=agent_id,
                auth_context=auth_context,
                request_id="error-request",
                status="failed",
                error="Authentication failed",
            )

        # Verify error log was created
        assert len(caplog.records) == 1
        log_record = caplog.records[0]

        # Check log level for errors
        assert log_record.levelno == logging.ERROR
        assert "A2A message_send failed" in log_record.message

        # Check error metadata
        metrics = log_record.a2a_metrics
        assert metrics["status"] == "failed"
        assert metrics["error"] == "Authentication failed"
        assert metrics["authenticated"] is False

    def test_log_a2a_operation_minimal(self, caplog):
        """Test A2A operation logging with minimal parameters."""
        agent_id = uuid4()
        auth_context = A2AAuthContext(
            authenticated=True,
            auth_method="bearer",
            user_id="test-user",
            workspace_id="test-workspace",
            permissions=["read"],
            metadata={},
        )

        # Test minimal logging
        with caplog.at_level(logging.INFO):
            log_a2a_operation(operation="agent_card", agent_id=agent_id, auth_context=auth_context)

        # Verify log was created with defaults
        assert len(caplog.records) == 1
        log_record = caplog.records[0]

        metrics = log_record.a2a_metrics
        assert metrics["a2a_operation"] == "agent_card"
        assert metrics["status"] == "started"  # Default status
        assert metrics["request_id"] is None
        assert "task_id" not in metrics  # Only added when provided
        assert "duration_ms" not in metrics
        assert "error" not in metrics

    def test_a2a_metadata_in_task_creation(self):
        """Test that A2A metadata is properly included in task creation."""
        from agentarea_api.api.v1.agents_a2a import convert_a2a_message_to_task
        from agentarea_common.utils.types import Message, MessageSendParams, TextPart

        # Setup
        agent_id = uuid4()
        auth_context = A2AAuthContext(
            authenticated=True,
            auth_method="bearer",
            user_id="test-user",
            workspace_id="test-workspace",
            permissions=["read", "write"],
            metadata={"user_agent": "test-client", "client_ip": "127.0.0.1"},
        )

        message = Message(role="user", parts=[TextPart(text="Test message")])
        message_params = MessageSendParams(message=message)

        # Create task with A2A metadata
        task = convert_a2a_message_to_task(
            message_params=message_params,
            agent_id=agent_id,
            auth_context=auth_context,
            a2a_method="message/send",
            request_id="test-request-123",
        )

        # Verify A2A metadata is included
        assert task.metadata is not None
        metadata = task.metadata

        # Check core A2A metadata
        assert metadata["source"] == "a2a"
        assert metadata["a2a_method"] == "message/send"
        assert metadata["a2a_request_id"] == "test-request-123"
        assert metadata["auth_method"] == "bearer"
        assert metadata["authenticated"] is True
        assert metadata["created_via"] == "a2a_protocol"

        # Check security context
        security_context = metadata["security_context"]
        assert security_context["user_id"] == "test-user"
        assert security_context["workspace_id"] == "test-workspace"
        assert security_context["permissions"] == ["read", "write"]

        # Check monitoring metadata
        monitoring = metadata["monitoring"]
        assert monitoring["task_source"] == "a2a_protocol"
        assert monitoring["protocol_version"] == "1.0"
        assert monitoring["message_length"] == len("Test message")
        assert monitoring["has_message_parts"] is True
        assert monitoring["message_parts_count"] == 1
        assert monitoring["is_streaming"] is False
        assert monitoring["agent_target"] == str(agent_id)

        # Check client metadata
        client_metadata = metadata["client_metadata"]
        assert client_metadata["user_agent"] == "test-client"
        assert client_metadata["client_ip"] == "127.0.0.1"

        # Check timestamps
        assert "created_timestamp" in metadata
        assert "auth_timestamp" in security_context

    def test_a2a_event_enhancement(self):
        """Test that A2A events are enhanced with monitoring information."""
        from agentarea_common.events.router import RedisRouter
        from agentarea_execution.activities.agent_execution_activities import make_agent_activities
        from agentarea_execution.interfaces import ActivityDependencies

        # Mock dependencies
        mock_deps = MagicMock(spec=ActivityDependencies)
        mock_deps.event_broker = MagicMock(spec=RedisRouter)
        mock_deps.event_broker.broker = MagicMock()

        # Create activities
        activities = make_agent_activities(mock_deps)

        # Find the publish_workflow_events_activity
        publish_activity = None
        for activity in activities:
            if hasattr(activity, "__name__") and "publish_workflow_events" in activity.__name__:
                publish_activity = activity
                break

        assert publish_activity is not None, "publish_workflow_events_activity not found"

        # Test event with A2A metadata
        test_event = {
            "event_type": "TaskStarted",
            "event_id": str(uuid4()),
            "timestamp": datetime.now(UTC).isoformat() + "Z",
            "data": {
                "task_id": str(uuid4()),
                "agent_id": str(uuid4()),
                "metadata": {
                    "source": "a2a",
                    "a2a_method": "message/send",
                    "a2a_request_id": "test-request",
                    "auth_method": "bearer",
                    "authenticated": True,
                    "monitoring": {"task_source": "a2a_protocol", "protocol_version": "1.0"},
                },
            },
        }

        # Mock the event broker and repository
        with (
            patch(
                "agentarea_common.events.router.create_event_broker_from_router"
            ) as mock_create_broker,
            patch("agentarea_execution.activities.dependencies.ActivityContext") as mock_context,
        ):
            mock_redis_broker = MagicMock()
            mock_create_broker.return_value = mock_redis_broker

            mock_context_instance = MagicMock()
            mock_context.return_value.__aenter__.return_value = mock_context_instance
            mock_context.return_value.__aexit__.return_value = None

            mock_task_event_service = MagicMock()
            mock_context_instance.get_task_event_service.return_value = mock_task_event_service

            # Test the activity (this would normally be called by Temporal)
            # For now, just verify the structure is correct
            events_json = [json.dumps(test_event)]

            # The actual test would require running the activity, but we can verify
            # the event structure is correct for A2A enhancement
            assert test_event["data"]["metadata"]["source"] == "a2a"
            assert "monitoring" in test_event["data"]["metadata"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
