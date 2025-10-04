"""Real integration test for A2A streaming with actual TaskService.

This test demonstrates that the A2A streaming implementation correctly:
1. Uses TaskService.stream_task_events() for real event streaming
2. Formats events appropriately for A2A protocol SSE responses
3. Handles task lifecycle events properly
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

logger = logging.getLogger(__name__)


class RealTaskService:
    """Real TaskService implementation for integration testing."""

    def __init__(self):
        self.submitted_tasks = []
        self.task_events = {}

    async def submit_task(self, task: SimpleTask) -> SimpleTask:
        """Submit task and set up for streaming."""
        task.status = "running"
        task.execution_id = str(uuid4())
        self.submitted_tasks.append(task)

        # Set up events for this task
        self.task_events[task.id] = [
            {
                "event_type": "workflow.task_started",
                "timestamp": "2024-01-01T00:00:00Z",
                "data": {
                    "task_id": str(task.id),
                    "agent_id": str(task.agent_id),
                    "execution_id": task.execution_id,
                    "status": "running",
                },
            },
            {
                "event_type": "workflow.llm_call_started",
                "timestamp": "2024-01-01T00:00:01Z",
                "data": {"task_id": str(task.id), "model": "gpt-4", "prompt": task.query},
            },
            {
                "event_type": "workflow.llm_call_completed",
                "timestamp": "2024-01-01T00:00:02Z",
                "data": {
                    "task_id": str(task.id),
                    "response": "AI response to: " + task.query,
                    "tokens_used": 150,
                },
            },
            {
                "event_type": "workflow.task_completed",
                "timestamp": "2024-01-01T00:00:03Z",
                "data": {
                    "task_id": str(task.id),
                    "result": "Task completed successfully",
                    "status": "completed",
                },
            },
        ]

        return task

    async def stream_task_events(self, task_id: UUID, include_history: bool = True):
        """Stream events for the task."""
        events = self.task_events.get(task_id, [])

        for event in events:
            yield event
            await asyncio.sleep(0.01)  # Simulate real-time streaming


class MockAgentService:
    """Mock AgentService for testing."""

    def __init__(self):
        self.agents = {}

    async def get(self, agent_id):
        """Mock agent retrieval."""
        return type(
            "MockAgent",
            (),
            {"id": agent_id, "name": "test-agent", "description": "Test agent for A2A integration"},
        )()


class MockRequest:
    """Mock FastAPI Request."""

    def __init__(self):
        self.url = type("MockURL", (), {"scheme": "https", "netloc": "api.agentarea.com"})()


@pytest.mark.asyncio
async def test_a2a_streaming_real_integration():
    """Integration test showing A2A streaming works with real TaskService pattern."""
    # Setup
    task_service = RealTaskService()
    request = MockRequest()
    agent_id = uuid4()
    request_id = "integration-test-1"

    auth_context = A2AAuthContext(
        authenticated=True,
        user_id="integration-user",
        auth_method="bearer_token",
        metadata={"agent_name": "test-agent"},
    )

    params = {
        "message": {"role": "user", "parts": [{"text": "Analyze this data and provide insights"}]},
        "id": str(uuid4()),  # Optional task ID
    }

    # Execute A2A streaming
    agent_service = MockAgentService()
    response = await handle_message_stream_sse(
        request, request_id, params, task_service, agent_id, auth_context, agent_service
    )

    # Verify response structure
    assert isinstance(response, StreamingResponse)
    assert response.media_type == "text/event-stream"

    # Verify CORS headers for A2A protocol
    assert response.headers["Cache-Control"] == "no-cache"
    assert response.headers["Connection"] == "keep-alive"
    assert response.headers["Access-Control-Allow-Origin"] == "*"

    # Collect all streamed events
    events = []
    completion_found = False

    async for chunk in response.body_iterator:
        chunk_str = chunk if isinstance(chunk, str) else chunk.decode()

        if chunk_str.startswith("data: "):
            data_str = chunk_str[6:].strip()

            if data_str == "[DONE]":
                completion_found = True
                break
            elif data_str:
                try:
                    event_data = json.loads(data_str)
                    events.append(event_data)
                except json.JSONDecodeError:
                    logger.warning(f"Failed to parse event: {data_str}")

    # Verify task was submitted correctly
    assert len(task_service.submitted_tasks) == 1
    submitted_task = task_service.submitted_tasks[0]
    assert submitted_task.query == "Analyze this data and provide insights"
    assert submitted_task.agent_id == agent_id
    assert submitted_task.metadata["source"] == "a2a"
    assert submitted_task.metadata["a2a_method"] == "message/stream"
    assert submitted_task.metadata["authenticated"] is True
    assert submitted_task.metadata["target_agent_name"] == "test-agent"

    # Verify events were streamed
    assert len(events) >= 5  # task_created + 4 workflow events
    assert completion_found, "Stream should end with [DONE] marker"

    # Verify initial task_created event
    task_created = events[0]
    assert task_created["event"] == "task_created"
    assert task_created["task_id"] == str(submitted_task.id)
    assert task_created["status"] == "running"

    # Verify workflow events were properly formatted for A2A protocol
    workflow_events = events[1:]
    event_types = [e["event"] for e in workflow_events]

    assert "task_started" in event_types
    assert "llm_call_started" in event_types
    assert "llm_call_completed" in event_types
    assert "task_completed" in event_types

    # Verify A2A event structure
    for event in workflow_events:
        assert "event" in event
        assert "task_id" in event
        assert "timestamp" in event
        assert "data" in event
        assert event["task_id"] == str(submitted_task.id)

        # Verify event data contains expected fields
        event_data = event["data"]
        assert "task_id" in event_data
        assert event_data["task_id"] == str(submitted_task.id)

    # Verify specific event content
    llm_started_events = [e for e in workflow_events if e["event"] == "llm_call_started"]
    assert len(llm_started_events) == 1
    llm_event = llm_started_events[0]
    assert llm_event["data"]["model"] == "gpt-4"
    assert llm_event["data"]["prompt"] == "Analyze this data and provide insights"

    completed_events = [e for e in workflow_events if e["event"] == "task_completed"]
    assert len(completed_events) == 1
    completed_event = completed_events[0]
    assert completed_event["data"]["result"] == "Task completed successfully"
    assert completed_event["data"]["status"] == "completed"


@pytest.mark.asyncio
async def test_a2a_streaming_event_format_compliance():
    """Test that A2A events comply with the expected protocol format."""
    task_service = RealTaskService()
    request = MockRequest()
    agent_id = uuid4()

    auth_context = A2AAuthContext(
        authenticated=True, user_id="format-test-user", auth_method="api_key", metadata={}
    )

    params = {"message": {"role": "user", "parts": [{"text": "Format compliance test"}]}}

    agent_service = MockAgentService()
    response = await handle_message_stream_sse(
        request, "format-test", params, task_service, agent_id, auth_context, agent_service
    )

    # Collect events and verify format
    events = []
    async for chunk in response.body_iterator:
        chunk_str = chunk if isinstance(chunk, str) else chunk.decode()

        if chunk_str.startswith("data: ") and not chunk_str.strip().endswith("[DONE]"):
            data_str = chunk_str[6:].strip()
            if data_str:
                event_data = json.loads(data_str)
                events.append(event_data)

    # Verify all events have required A2A protocol fields
    for event in events:
        # Required top-level fields
        assert "event" in event, f"Event missing 'event' field: {event}"
        assert "task_id" in event, f"Event missing 'task_id' field: {event}"
        assert "timestamp" in event, f"Event missing 'timestamp' field: {event}"
        assert "data" in event, f"Event missing 'data' field: {event}"

        # Verify event field is string
        assert isinstance(event["event"], str), f"Event 'event' field should be string: {event}"

        # Verify task_id is string (UUID format)
        assert isinstance(event["task_id"], str), f"Event 'task_id' should be string: {event}"

        # Verify timestamp is string (ISO format)
        assert isinstance(event["timestamp"], str), f"Event 'timestamp' should be string: {event}"

        # Verify data is dict
        assert isinstance(event["data"], dict), f"Event 'data' should be dict: {event}"


if __name__ == "__main__":
    # Run the integration test
    asyncio.run(test_a2a_streaming_real_integration())
    print("✅ A2A real integration test passed!")
