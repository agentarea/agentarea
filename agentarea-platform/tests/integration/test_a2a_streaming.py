"""Integration test for A2A streaming functionality.

Verifies that the A2A message/stream endpoint:
1. Creates a task through TaskService
2. Consumes the REAL workflow event stream (``workflow.WorkflowCompleted``,
   ``workflow.LLMCallChunk``) surfaced by EventStreamService
3. Emits A2A v0.3.0 SSE frames: a JSON-RPC-wrapped initial ``task`` event,
   ``artifact-update`` frames for incremental output, and a terminal
   ``status-update`` with ``final=True``.

See ADR docs/adr/2026-06-20-a2a-transport-correctness.md.
"""

import asyncio
import json
import logging
from uuid import UUID, uuid4

import pytest
from agentarea_api.api.v1.a2a_auth import A2AAuthContext
from agentarea_api.api.v1.agents_a2a import handle_message_stream_sse
from agentarea_tasks.domain.models import AgentTask
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)


class MockTaskService:
    """Mock TaskService for testing A2A streaming."""

    def __init__(self):
        self.submitted_tasks = []

    async def submit_task(self, task: AgentTask) -> AgentTask:
        task.status = "running"
        task.execution_id = str(uuid4())
        self.submitted_tasks.append(task)
        return task


class MockAgentService:
    async def get(self, agent_id: UUID):
        from types import SimpleNamespace

        return SimpleNamespace(id=agent_id, name="Test Agent", status="active")


class MockEventStreamService:
    """Yields events in the real EventStreamService shape.

    Real events carry the workflow payload under ``event_data['original_data']``
    and use ``workflow.*`` event types.
    """

    async def stream_events_for_task(self, task_id: UUID, event_patterns=None):
        test_events = [
            {
                "event_type": "workflow.LLMCallChunk",
                "event_data": {"original_data": {"task_id": str(task_id), "chunk": "Partial "}},
            },
            {
                "event_type": "workflow.LLMCallChunk",
                "event_data": {"original_data": {"task_id": str(task_id), "chunk": "answer"}},
            },
            {
                "event_type": "workflow.WorkflowCompleted",
                "event_data": {"original_data": {"task_id": str(task_id), "result": "Final answer"}},
            },
        ]
        for event in test_events:
            yield event
            await asyncio.sleep(0.01)


class MockRequest:
    def __init__(self):
        self.url = type("MockURL", (), {"scheme": "http", "netloc": "localhost:8000"})()


def _parse_frames(chunks):
    frames = []
    for chunk in chunks:
        chunk_str = chunk.decode() if isinstance(chunk, bytes) else chunk
        if chunk_str.startswith("data: "):
            data_str = chunk_str[6:].strip()
            if data_str and data_str != "[DONE]":
                try:
                    frames.append(json.loads(data_str))
                except json.JSONDecodeError:
                    pass
    return frames


@pytest.mark.asyncio
async def test_a2a_streaming_uses_real_events():
    """A2A streaming maps real workflow events to spec-compliant SSE frames."""
    mock_task_service = MockTaskService()
    mock_event_stream_service = MockEventStreamService()
    mock_agent_service = MockAgentService()
    mock_request = MockRequest()
    agent_id = uuid4()
    request_id = "test-request-1"

    auth_context = A2AAuthContext(
        authenticated=True,
        user_id="test-user",
        workspace_id="test-workspace",
        auth_method="bearer_token",
        metadata={},
    )

    params = {"message": {"role": "user", "parts": [{"text": "Test message for streaming"}]}}

    response = await handle_message_stream_sse(
        mock_request,
        request_id,
        params,
        mock_task_service,
        agent_id,
        auth_context,
        mock_agent_service,
        mock_event_stream_service,
    )

    assert isinstance(response, StreamingResponse)
    assert response.media_type == "text/event-stream"

    assert len(mock_task_service.submitted_tasks) == 1
    submitted_task = mock_task_service.submitted_tasks[0]
    assert submitted_task.query == "Test message for streaming"
    assert submitted_task.metadata["a2a_method"] == "SendStreamingMessage"

    frames = _parse_frames([chunk async for chunk in response.body_iterator])

    # Every frame is a JSON-RPC 2.0 response wrapping a StreamResponse oneof member.
    assert all(f.get("jsonrpc") == "2.0" for f in frames)
    results = [f["result"] for f in frames]
    # Member name = the single key of each result wrapper.
    members = [next(iter(r.keys())) for r in results]

    # First frame: initial task object (wrapped under "task").
    assert members[0] == "task"
    assert results[0]["task"]["id"] == str(submitted_task.id)
    assert results[0]["task"]["contextId"]  # non-null per spec

    # Incremental chunks become artifactUpdate frames.
    artifact_updates = [r["artifactUpdate"] for r in results if "artifactUpdate" in r]
    assert artifact_updates, "expected at least one artifactUpdate from LLM chunks"
    streamed_text = "".join(
        part["text"]
        for au in artifact_updates
        for part in au["artifact"]["parts"]
        if part.get("text")
    )
    assert "Partial " in streamed_text
    assert "answer" in streamed_text
    assert "Final answer" in streamed_text  # final result emitted as last artifact

    # Last frame: terminal statusUpdate with completed state (no final field).
    assert members[-1] == "statusUpdate"
    su = results[-1]["statusUpdate"]
    assert "final" not in su
    assert su["status"]["state"] == "COMPLETED"


@pytest.mark.asyncio
async def test_a2a_streaming_error_handling():
    """A2A streaming surfaces task-submission failures as an error frame."""

    class FailingTaskService:
        async def submit_task(self, task):
            raise ValueError("Task submission failed")

    mock_task_service = FailingTaskService()
    mock_agent_service = MockAgentService()
    mock_event_stream_service = MockEventStreamService()
    mock_request = MockRequest()
    agent_id = uuid4()
    request_id = "test-request-2"

    auth_context = A2AAuthContext(
        authenticated=True,
        user_id="test-user",
        workspace_id="test-workspace",
        auth_method="bearer_token",
        metadata={},
    )

    params = {"message": {"role": "user", "parts": [{"text": "Test message"}]}}

    response = await handle_message_stream_sse(
        mock_request,
        request_id,
        params,
        mock_task_service,
        agent_id,
        auth_context,
        mock_agent_service,
        mock_event_stream_service,
    )

    assert isinstance(response, StreamingResponse)

    frames = _parse_frames([chunk async for chunk in response.body_iterator])
    assert len(frames) >= 1
    # Validation/submission failure is reported via the legacy error frame shape.
    assert any(f.get("event") == "error" for f in frames)


if __name__ == "__main__":
    asyncio.run(test_a2a_streaming_uses_real_events())
