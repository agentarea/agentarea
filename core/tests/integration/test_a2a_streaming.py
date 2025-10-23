"""Integration test for A2A streaming functionality.

This test verifies that the A2A message/stream endpoint properly:
1. Creates tasks through TaskService
2. Streams real events using TaskService.stream_task_events()
3. Formats events appropriately for A2A protocol SSE responses
"""

import asyncio
import json
import logging
from uuid import UUID, uuid4

import pytest
from agentarea_api.api.v1.a2a_auth import A2AAuthContext
from agentarea_api.api.v1.agents_a2a import handle_message_stream_sse
from agentarea_tasks.domain.models import SimpleTask
from fastapi.responses import StreamingResponse
from agentarea_common.events.event_stream_service import EventStreamService
from agentarea_agents.application.agent_service import AgentService

logger = logging.getLogger(__name__)


class MockTaskService:
    """Mock TaskService for testing A2A streaming."""

    def __init__(self):
        self.submitted_tasks = []
        self.events = []

    async def submit_task(self, task: SimpleTask) -> SimpleTask:
        """Mock task submission."""
        task.status = "running"
        task.execution_id = str(uuid4())
        self.submitted_tasks.append(task)
        return task


class MockAgentService:
    """Mock AgentService for testing A2A streaming."""

    async def get(self, agent_id: UUID):
        """Mock getting an agent."""
        return {"id": agent_id, "name": "Test Agent", "status": "active"}


class MockEventStreamService:
    """Mock EventStreamService for testing A2A streaming."""

    async def stream_events_for_task(self, task_id: UUID, event_patterns=None):
        """Mock event streaming that yields test events."""
        # Yield some test events
        test_events = [
            {
                "event_type": "workflow.task_started",
                "timestamp": "2024-01-01T00:00:00Z",
                "data": {
                    "task_id": str(task_id),
                    "agent_id": "test-agent",
                    "execution_id": "test-execution",
                },
            },
            {
                "event_type": "workflow.llm_call_started",
                "timestamp": "2024-01-01T00:00:01Z",
                "data": {"task_id": str(task_id), "model": "gpt-4", "prompt": "Test prompt"},
            },
            {
                "event_type": "workflow.task_completed",
                "timestamp": "2024-01-01T00:00:02Z",
                "data": {"task_id": str(task_id), "result": "Test result"},
            },
        ]

        for event in test_events:
            yield event
            await asyncio.sleep(0.01)  # Small delay to simulate real streaming


class MockRequest:
    """Mock FastAPI Request for testing."""

    def __init__(self):
        self.url = type("MockURL", (), {"scheme": "http", "netloc": "localhost:8000"})()


@pytest.mark.asyncio
async def test_a2a_streaming_uses_real_events():
    """Test that A2A streaming uses real EventStreamService event streaming."""
    # Setup
    mock_task_service = MockTaskService()
    mock_event_stream_service = MockEventStreamService()
    mock_agent_service = MockAgentService()
    mock_request = MockRequest()
    agent_id = uuid4()
    request_id = "test-request-1"

    # Create auth context
    auth_context = A2AAuthContext(
        authenticated=True, user_id="test-user", auth_method="bearer_token", metadata={}
    )

    # Test parameters
    params = {"message": {"role": "user", "parts": [{"text": "Test message for streaming"}]}}

    # Call the A2A streaming handler
    response = await handle_message_stream_sse(
        mock_request, request_id, params, mock_task_service, agent_id, auth_context, mock_agent_service, mock_event_stream_service
    )

    # Verify response is StreamingResponse
    assert isinstance(response, StreamingResponse)
    assert response.media_type == "text/event-stream"

    # Verify task was submitted
    assert len(mock_task_service.submitted_tasks) == 1
    submitted_task = mock_task_service.submitted_tasks[0]
    assert submitted_task.query == "Test message for streaming"
    assert submitted_task.agent_id == agent_id
    assert submitted_task.metadata["source"] == "a2a"
    assert submitted_task.metadata["a2a_method"] == "message/stream"

    # Collect streamed events
    events = []
    async for chunk in response.body_iterator:
        # Handle both string and bytes
        if isinstance(chunk, bytes):
            chunk_str = chunk.decode()
        else:
            chunk_str = chunk

        if chunk_str.startswith("data: "):
            data_str = chunk_str[6:].strip()
            if data_str and data_str != "[DONE]":
                try:
                    event_data = json.loads(data_str)
                    events.append(event_data)
                except json.JSONDecodeError:
                    pass

    # Verify events were streamed
    assert len(events) >= 4  # Initial task_created + 3 test events

    # Check initial task created event
    task_created_event = events[0]
    assert task_created_event["event"] == "task_created"
    assert task_created_event["task_id"] == str(submitted_task.id)

    # Check that real events from TaskService were streamed
    event_types = [event.get("event") for event in events[1:]]
    assert "task_started" in event_types
    assert "llm_call_started" in event_types
    assert "task_completed" in event_types

    # Verify A2A event format
    for event in events[1:]:
        assert "event" in event
        assert "task_id" in event
        assert "timestamp" in event
        assert "data" in event


@pytest.mark.asyncio
async def test_a2a_streaming_error_handling():
    """Test A2A streaming error handling."""

    # Setup with failing task service
    class FailingTaskService:
        async def submit_task(self, task):
            raise ValueError("Task submission failed")

    mock_task_service = FailingTaskService()
    mock_request = MockRequest()
    agent_id = uuid4()
    request_id = "test-request-2"

    auth_context = A2AAuthContext(
        authenticated=True, user_id="test-user", auth_method="bearer_token", metadata={}
    )

    params = {"message": {"role": "user", "parts": [{"text": "Test message"}]}}

    # Call the handler
    response = await handle_message_stream_sse(
        mock_request, request_id, params, mock_task_service, agent_id, auth_context
    )

    # Verify error response
    assert isinstance(response, StreamingResponse)

    # Collect error events
    events = []
    async for chunk in response.body_iterator:
        # Handle both string and bytes
        if isinstance(chunk, bytes):
            chunk_str = chunk.decode()
        else:
            chunk_str = chunk

        if chunk_str.startswith("data: "):
            data_str = chunk_str[6:].strip()
            if data_str:
                try:
                    event_data = json.loads(data_str)
                    events.append(event_data)
                except json.JSONDecodeError:
                    pass

    # Should have error event
    assert len(events) >= 1
    error_event = events[0]
    assert error_event["event"] == "error"
    assert "Task submission failed" in error_event["message"]


if __name__ == "__main__":
    # Run the test
    asyncio.run(test_a2a_streaming_uses_real_events())
    print("✅ A2A streaming test passed!")
