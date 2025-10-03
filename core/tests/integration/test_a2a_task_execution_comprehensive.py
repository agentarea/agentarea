"""Comprehensive integration tests for A2A task execution.

This test suite verifies that the A2A protocol endpoints properly:
1. Create tasks through JSON-RPC endpoints
2. Execute tasks through Temporal workflows
3. Stream real events during task execution
4. Handle error scenarios and authentication failures

Requirements tested:
- 1.1: A2A protocol interface for agent communication
- 1.2: Message routing through event system
- 1.3: Task delegation and execution
- 1.4: Message queuing and delivery
- 2.1: Authentication and authorization
- 2.2: Security context and audit logging
"""

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from agentarea_api.api.v1.a2a_auth import A2AAuthContext, A2APermissions
from agentarea_api.api.v1.agents_a2a import (
    handle_agent_jsonrpc,
    handle_message_send,
    handle_message_stream_sse,
    handle_task_cancel,
    handle_task_get,
)
from agentarea_common.utils.types import (
    JSONRPCResponse,
)
from agentarea_tasks.domain.models import SimpleTask
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)


class MockAgent:
    """Mock agent for testing."""

    def __init__(self, agent_id: UUID, name: str = "test-agent", status: str = "active"):
        self.id = agent_id
        self.name = name
        self.description = f"Test agent {name}"
        self.status = status


class MockAgentService:
    """Mock AgentService for testing."""

    def __init__(self):
        self.agents = {}

    def add_agent(self, agent: MockAgent):
        """Add an agent to the mock service."""
        self.agents[agent.id] = agent

    async def get(self, agent_id: UUID) -> MockAgent | None:
        """Get agent by ID."""
        return self.agents.get(agent_id)


class MockTaskService:
    """Mock TaskService that simulates Temporal workflow execution."""

    def __init__(self):
        self.submitted_tasks = []
        self.task_events = {}
        self.cancelled_tasks = []
        self.workflow_statuses = {}
        self.should_fail_submission = False
        self.should_fail_streaming = False

    async def submit_task(self, task: SimpleTask) -> SimpleTask:
        """Submit task and simulate Temporal workflow execution."""
        if self.should_fail_submission:
            raise ValueError("Task submission failed")

        # Simulate task processing
        task.status = "running"
        task.execution_id = str(uuid4())
        self.submitted_tasks.append(task)

        # Set up events for streaming
        self._setup_task_events(task)

        return task

    def _setup_task_events(self, task: SimpleTask):
        """Set up mock events for task streaming."""
        self.task_events[task.id] = [
            {
                "event_type": "workflow.task_started",
                "timestamp": datetime.now(UTC).isoformat(),
                "data": {
                    "task_id": str(task.id),
                    "agent_id": str(task.agent_id),
                    "execution_id": task.execution_id,
                    "status": "running",
                    "aggregate_id": str(task.id),
                },
            },
            {
                "event_type": "workflow.llm_call_started",
                "timestamp": datetime.now(UTC).isoformat(),
                "data": {
                    "task_id": str(task.id),
                    "model": "gpt-4",
                    "prompt": task.query,
                    "aggregate_id": str(task.id),
                },
            },
            {
                "event_type": "workflow.llm_call_completed",
                "timestamp": datetime.now(UTC).isoformat(),
                "data": {
                    "task_id": str(task.id),
                    "response": f"AI response to: {task.query}",
                    "tokens_used": 150,
                    "aggregate_id": str(task.id),
                },
            },
            {
                "event_type": "workflow.task_completed",
                "timestamp": datetime.now(UTC).isoformat(),
                "data": {
                    "task_id": str(task.id),
                    "result": "Task completed successfully",
                    "status": "completed",
                    "aggregate_id": str(task.id),
                },
            },
        ]

    async def stream_task_events(
        self, task_id: UUID, include_history: bool = True
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Stream events for the task."""
        if self.should_fail_streaming:
            raise RuntimeError("Event streaming failed")

        events = self.task_events.get(task_id, [])

        for event in events:
            yield event
            await asyncio.sleep(0.01)  # Simulate real-time streaming

    async def get_task_with_workflow_status(self, task_id: UUID) -> SimpleTask | None:
        """Get task with current workflow status."""
        # Find task in submitted tasks
        task = None
        for submitted_task in self.submitted_tasks:
            if submitted_task.id == task_id:
                task = submitted_task
                break

        if not task:
            return None

        # Apply workflow status if available
        workflow_status = self.workflow_statuses.get(task_id, {})
        if workflow_status:
            task.status = workflow_status.get("status", task.status)
            if workflow_status.get("result"):
                task.result = workflow_status["result"]

        return task

    async def cancel_task(self, task_id: UUID) -> bool:
        """Cancel a task."""
        task = await self.get_task_with_workflow_status(task_id)
        if not task:
            return False

        if task.status in ["completed", "failed", "cancelled"]:
            return False

        # Update the task status in the submitted_tasks list
        for submitted_task in self.submitted_tasks:
            if submitted_task.id == task_id:
                submitted_task.status = "cancelled"
                break

        # Also update workflow status
        self.workflow_statuses[task_id] = {"status": "cancelled"}
        self.cancelled_tasks.append(task_id)
        return True

    def set_workflow_status(self, task_id: UUID, status: str, result: dict = None):
        """Set workflow status for a task."""
        self.workflow_statuses[task_id] = {"status": status, "result": result}


class MockRequest:
    """Mock FastAPI Request for testing."""

    def __init__(self, headers: dict = None, body_data: dict = None):
        self.headers = headers or {}
        self.client = type("MockClient", (), {"host": "127.0.0.1"})()
        self.url = type("MockURL", (), {"scheme": "https", "netloc": "api.agentarea.com"})()
        self._body_data = body_data

    async def body(self) -> bytes:
        """Return mock request body."""
        if self._body_data:
            return json.dumps(self._body_data).encode()
        return b""


def create_auth_context(
    authenticated: bool = True,
    user_id: str = "test-user",
    workspace_id: str = "default",
    permissions: list[str] = None,
    auth_method: str = "bearer_token",
) -> A2AAuthContext:
    """Create A2A authentication context for testing."""
    return A2AAuthContext(
        authenticated=authenticated,
        user_id=user_id,
        workspace_id=workspace_id,
        permissions=permissions or A2APermissions.USER_PERMISSIONS,
        auth_method=auth_method,
        metadata={"agent_name": "test-agent"},
    )


@pytest.mark.asyncio
async def test_a2a_task_creation_through_jsonrpc():
    """Test A2A task creation through JSON-RPC endpoints.

    Requirements: 1.1, 1.3, 2.1
    """
    # Setup
    agent_id = uuid4()
    task_service = MockTaskService()
    agent_service = MockAgentService()
    agent_service.add_agent(MockAgent(agent_id))

    # Create JSON-RPC request for task/send
    request_data = {
        "jsonrpc": "2.0",
        "method": "tasks/send",
        "params": {
            "message": {
                "role": "user",
                "parts": [{"type": "text", "text": "Analyze this data and provide insights"}],
            }
        },
        "id": "test-request-1",
    }

    request = MockRequest(headers={"authorization": "Bearer test-token"}, body_data=request_data)

    auth_context = create_auth_context()

    # Mock the authentication dependency
    with patch("agentarea_api.api.v1.agents_a2a.set_user_context_from_a2a_auth"):
        # Execute JSON-RPC handler
        response = await handle_agent_jsonrpc(
            agent_id=agent_id,
            request=request,
            auth_context=auth_context,
            task_service=task_service,
            agent_service=agent_service,
        )

    # Verify response structure
    assert isinstance(response, JSONRPCResponse)
    assert response.jsonrpc == "2.0"
    assert response.id == "test-request-1"
    assert response.result is not None
    assert response.error is None

    # Verify task was created and submitted
    assert len(task_service.submitted_tasks) == 1
    submitted_task = task_service.submitted_tasks[0]

    # Verify task properties
    assert submitted_task.query == "Analyze this data and provide insights"
    assert submitted_task.agent_id == agent_id
    assert submitted_task.user_id == "test-user"
    assert submitted_task.workspace_id == "default"
    assert submitted_task.status == "running"

    # Verify A2A metadata
    assert submitted_task.metadata["source"] == "a2a"
    assert submitted_task.metadata["a2a_method"] == "tasks/send"
    assert submitted_task.metadata["authenticated"] is True
    assert submitted_task.metadata["security_context"]["user_id"] == "test-user"

    # Verify A2A task response format
    a2a_task = response.result
    assert a2a_task.id == str(submitted_task.id)
    assert a2a_task.status.state.value == "submitted"


@pytest.mark.asyncio
async def test_a2a_message_send_creates_temporal_task():
    """Test that A2A message/send creates tasks that execute through Temporal workflows.

    Requirements: 1.1, 1.2, 1.3
    """
    # Setup
    agent_id = uuid4()
    task_service = MockTaskService()
    agent_service = MockAgentService()
    agent_service.add_agent(MockAgent(agent_id))

    auth_context = create_auth_context()

    params = {
        "message": {
            "role": "user",
            "parts": [{"type": "text", "text": "Process this message through Temporal workflow"}],
        }
    }

    # Mock the authentication dependency
    with patch("agentarea_api.api.v1.agents_a2a.set_user_context_from_a2a_auth"):
        # Execute message/send handler
        response = await handle_message_send(
            request_id="message-test",
            params=params,
            task_service=task_service,
            agent_id=agent_id,
            auth_context=auth_context,
            agent_service=agent_service,
        )

    # Verify successful response
    assert response.jsonrpc == "2.0"
    assert response.id == "message-test"
    assert response.result is not None

    # Verify task was submitted to Temporal workflow
    assert len(task_service.submitted_tasks) == 1
    submitted_task = task_service.submitted_tasks[0]

    # Verify task has execution_id (indicates Temporal workflow submission)
    assert submitted_task.execution_id is not None
    assert submitted_task.status == "running"

    # Verify A2A metadata for workflow tracking
    assert submitted_task.metadata["a2a_method"] == "message/send"
    assert submitted_task.metadata["monitoring"]["task_source"] == "a2a_protocol"
    assert submitted_task.metadata["monitoring"]["protocol_version"] == "1.0"

    # Verify events were set up for streaming
    assert submitted_task.id in task_service.task_events
    events = task_service.task_events[submitted_task.id]
    assert len(events) == 4  # task_started, llm_call_started, llm_call_completed, task_completed

    # Verify workflow event structure
    task_started_event = events[0]
    assert task_started_event["event_type"] == "workflow.task_started"
    assert task_started_event["data"]["task_id"] == str(submitted_task.id)
    assert task_started_event["data"]["execution_id"] == submitted_task.execution_id


@pytest.mark.asyncio
async def test_a2a_task_streaming_with_real_events():
    """Test A2A task streaming with real events from TaskService.

    Requirements: 1.1, 1.4, 5.1, 5.2
    """
    # Setup
    agent_id = uuid4()
    task_service = MockTaskService()
    agent_service = MockAgentService()
    agent_service.add_agent(MockAgent(agent_id))

    request = MockRequest()
    auth_context = create_auth_context()

    params = {
        "message": {
            "role": "user",
            "parts": [{"type": "text", "text": "Stream events for this task"}],
        }
    }

    # Mock the authentication dependency
    with patch("agentarea_api.api.v1.agents_a2a.set_user_context_from_a2a_auth"):
        # Execute streaming handler
        response = await handle_message_stream_sse(
            request=request,
            request_id="stream-test",
            params=params,
            task_service=task_service,
            agent_id=agent_id,
            auth_context=auth_context,
            agent_service=agent_service,
        )

    # Verify streaming response
    assert isinstance(response, StreamingResponse)
    assert response.media_type == "text/event-stream"

    # Verify CORS headers for A2A protocol
    assert response.headers["Cache-Control"] == "no-cache"
    assert response.headers["Connection"] == "keep-alive"
    assert response.headers["Access-Control-Allow-Origin"] == "*"

    # Verify task was created
    assert len(task_service.submitted_tasks) == 1
    submitted_task = task_service.submitted_tasks[0]

    # Collect streamed events
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

    # Verify events were streamed
    assert len(events) >= 5  # task_created + 4 workflow events
    assert completion_found, "Stream should end with [DONE] marker"

    # Verify initial task_created event
    task_created = events[0]
    assert task_created["event"] == "task_created"
    assert task_created["task_id"] == str(submitted_task.id)
    assert task_created["status"] == "running"
    assert task_created["data"]["a2a_metadata"]["source"] == "a2a"

    # Verify workflow events were properly formatted for A2A protocol
    workflow_events = events[1:]
    event_types = [e["event"] for e in workflow_events]

    assert "task_started" in event_types
    assert "llm_call_started" in event_types
    assert "llm_call_completed" in event_types
    assert "task_completed" in event_types

    # Verify A2A event structure compliance
    for event in workflow_events:
        assert "event" in event
        assert "task_id" in event
        assert "timestamp" in event
        assert "data" in event
        assert event["task_id"] == str(submitted_task.id)

        # Verify A2A metadata is added to events
        event_data = event["data"]
        assert "a2a_metadata" in event_data
        assert event_data["a2a_metadata"]["source"] == "a2a"
        assert event_data["a2a_metadata"]["method"] == "message/stream"
        assert event_data["a2a_metadata"]["request_id"] == "stream-test"


@pytest.mark.asyncio
async def test_a2a_task_management_endpoints():
    """Test A2A task management endpoints (get/cancel) with workflow status.

    Requirements: 1.1, 1.5, 4.3
    """
    # Setup
    agent_id = uuid4()
    task_service = MockTaskService()
    agent_service = MockAgentService()
    agent_service.add_agent(MockAgent(agent_id))

    # Create a task
    task_id = uuid4()
    task = SimpleTask(
        id=task_id,
        title="Test Task",
        description="Task for management testing",
        query="Test query",
        user_id="test-user",
        agent_id=agent_id,
        status="running",
    )
    task_service.submitted_tasks.append(task)

    auth_context = create_auth_context()

    # Test task/get endpoint
    get_params = {"id": str(task_id)}
    get_response = await handle_task_get(
        request_id="get-test",
        params=get_params,
        task_service=task_service,
        agent_id=agent_id,
        auth_context=auth_context,
    )

    # Verify get response
    assert get_response.jsonrpc == "2.0"
    assert get_response.id == "get-test"
    assert get_response.result is not None

    a2a_task = get_response.result
    assert a2a_task.id == str(task_id)
    assert a2a_task.status.state.value == "working"  # "running" maps to "working" in A2A

    # Test task/cancel endpoint
    cancel_params = {"id": str(task_id)}
    cancel_response = await handle_task_cancel(
        request_id="cancel-test",
        params=cancel_params,
        task_service=task_service,
        agent_id=agent_id,
        auth_context=auth_context,
    )

    # Verify cancel response
    assert cancel_response.jsonrpc == "2.0"
    assert cancel_response.id == "cancel-test"
    assert cancel_response.result is not None

    cancelled_task = cancel_response.result
    assert cancelled_task.id == str(task_id)
    assert cancelled_task.status.state.value == "canceled"  # A2A uses "canceled" (one 'l')

    # Verify task was actually cancelled
    assert task_id in task_service.cancelled_tasks


@pytest.mark.asyncio
async def test_a2a_authentication_failures():
    """Test A2A authentication failure scenarios.

    Requirements: 2.1, 2.2
    """
    # Setup
    agent_id = uuid4()
    task_service = MockTaskService()
    agent_service = MockAgentService()
    agent_service.add_agent(MockAgent(agent_id))

    # Test 1: Unauthenticated request
    unauthenticated_context = create_auth_context(
        authenticated=False, user_id=None, permissions=A2APermissions.PUBLIC_PERMISSIONS
    )

    params = {"message": {"role": "user", "parts": [{"type": "text", "text": "This should fail"}]}}

    with patch("agentarea_api.api.v1.agents_a2a.set_user_context_from_a2a_auth"):
        response = await handle_message_send(
            request_id="unauth-test",
            params=params,
            task_service=task_service,
            agent_id=agent_id,
            auth_context=unauthenticated_context,
            agent_service=agent_service,
        )

    # Should still work but with anonymous user context
    assert response.jsonrpc == "2.0"
    assert response.result is not None

    # Verify task was created with anonymous user
    assert len(task_service.submitted_tasks) == 1
    submitted_task = task_service.submitted_tasks[0]
    assert submitted_task.user_id == "a2a_anonymous"
    assert submitted_task.metadata["authenticated"] is False

    # Test 2: Insufficient permissions (if we had permission checks)
    # This would be tested if we had stricter permission enforcement

    # Test 3: Invalid agent ID
    invalid_agent_id = uuid4()

    with patch("agentarea_api.api.v1.agents_a2a.set_user_context_from_a2a_auth"):
        response = await handle_message_send(
            request_id="invalid-agent-test",
            params=params,
            task_service=task_service,
            agent_id=invalid_agent_id,
            auth_context=create_auth_context(),
            agent_service=agent_service,
        )

    # Should return error for non-existent agent
    assert response.jsonrpc == "2.0"
    assert response.error is not None
    assert response.error.code == -32602
    assert "does not exist" in response.error.message


@pytest.mark.asyncio
async def test_a2a_error_scenarios():
    """Test various A2A error scenarios.

    Requirements: 2.1, 2.2, 2.3
    """
    # Setup
    agent_id = uuid4()
    agent_service = MockAgentService()
    agent_service.add_agent(MockAgent(agent_id))
    auth_context = create_auth_context()

    # Test 1: Task service submission failure
    failing_task_service = MockTaskService()
    failing_task_service.should_fail_submission = True

    params = {"message": {"role": "user", "parts": [{"type": "text", "text": "This will fail"}]}}

    with patch("agentarea_api.api.v1.agents_a2a.set_user_context_from_a2a_auth"):
        response = await handle_message_send(
            request_id="fail-test",
            params=params,
            task_service=failing_task_service,
            agent_id=agent_id,
            auth_context=auth_context,
            agent_service=agent_service,
        )

    # Verify error response
    assert response.jsonrpc == "2.0"
    assert response.error is not None
    assert response.error.code == -32602
    assert "Task submission failed" in response.error.message

    # Test 2: Invalid parameters
    invalid_params = {
        "message": {
            "role": "user",
            "parts": [],  # Empty parts should fail validation
        }
    }

    with patch("agentarea_api.api.v1.agents_a2a.set_user_context_from_a2a_auth"):
        response = await handle_message_send(
            request_id="invalid-params-test",
            params=invalid_params,
            task_service=MockTaskService(),
            agent_id=agent_id,
            auth_context=auth_context,
            agent_service=agent_service,
        )

    # Verify validation error
    assert response.jsonrpc == "2.0"
    assert response.error is not None
    assert response.error.code == -32602
    assert "at least one part" in response.error.message

    # Test 3: Streaming failure
    streaming_task_service = MockTaskService()
    streaming_task_service.should_fail_streaming = True

    request = MockRequest()

    with patch("agentarea_api.api.v1.agents_a2a.set_user_context_from_a2a_auth"):
        response = await handle_message_stream_sse(
            request=request,
            request_id="stream-fail-test",
            params=params,
            task_service=streaming_task_service,
            agent_id=agent_id,
            auth_context=auth_context,
            agent_service=agent_service,
        )

    # Verify streaming error response
    assert isinstance(response, StreamingResponse)

    # Collect error events
    events = []
    async for chunk in response.body_iterator:
        chunk_str = chunk if isinstance(chunk, str) else chunk.decode()

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
    error_event = events[-1]  # Last event should be error
    assert error_event["event"] == "error"
    assert "Event streaming failed" in error_event["message"]


@pytest.mark.asyncio
async def test_a2a_jsonrpc_protocol_compliance():
    """Test A2A JSON-RPC protocol compliance.

    Requirements: 1.1, 2.3
    """
    # Setup
    agent_id = uuid4()
    task_service = MockTaskService()
    agent_service = MockAgentService()
    agent_service.add_agent(MockAgent(agent_id))

    # Test 1: Valid JSON-RPC request
    valid_request_data = {
        "jsonrpc": "2.0",
        "method": "message/send",
        "params": {
            "message": {
                "role": "user",
                "parts": [{"type": "text", "text": "Valid JSON-RPC request"}],
            }
        },
        "id": "protocol-test-1",
    }

    request = MockRequest(body_data=valid_request_data)
    auth_context = create_auth_context()

    with patch("agentarea_api.api.v1.agents_a2a.set_user_context_from_a2a_auth"):
        response = await handle_agent_jsonrpc(
            agent_id=agent_id,
            request=request,
            auth_context=auth_context,
            task_service=task_service,
            agent_service=agent_service,
        )

    # Verify JSON-RPC response format
    assert isinstance(response, JSONRPCResponse)
    assert response.jsonrpc == "2.0"
    assert response.id == "protocol-test-1"
    assert response.result is not None
    assert response.error is None

    # Test 2: Invalid JSON-RPC request (missing required fields)
    invalid_request_data = {
        "jsonrpc": "2.0",
        # Missing method field - this should cause validation error
        "params": {"message": {"role": "user", "parts": [{"type": "text", "text": "Invalid"}]}},
        "id": "protocol-test-2",
    }

    request = MockRequest(body_data=invalid_request_data)

    with patch("agentarea_api.api.v1.agents_a2a.set_user_context_from_a2a_auth"):
        response = await handle_agent_jsonrpc(
            agent_id=agent_id,
            request=request,
            auth_context=auth_context,
            task_service=task_service,
            agent_service=agent_service,
        )

    # Verify error response format
    assert isinstance(response, JSONRPCResponse)
    assert response.jsonrpc == "2.0"
    assert response.id == "protocol-test-2"
    assert response.error is not None
    assert response.error.code == -32600  # Invalid Request
    assert "Invalid request" in response.error.message

    # Test 3: Method not found
    unknown_method_data = {
        "jsonrpc": "2.0",
        "method": "unknown/method",
        "params": {},
        "id": "protocol-test-3",
    }

    request = MockRequest(body_data=unknown_method_data)

    with patch("agentarea_api.api.v1.agents_a2a.set_user_context_from_a2a_auth"):
        response = await handle_agent_jsonrpc(
            agent_id=agent_id,
            request=request,
            auth_context=auth_context,
            task_service=task_service,
            agent_service=agent_service,
        )

    # Verify method not found error
    assert response.error is not None
    assert response.error.code == -32601  # Method not found
    assert "Method not found" in response.error.message


@pytest.mark.asyncio
async def test_a2a_task_workflow_status_integration():
    """Test that A2A tasks properly integrate with Temporal workflow status.

    Requirements: 4.1, 4.2, 4.3
    """
    # Setup
    agent_id = uuid4()
    task_service = MockTaskService()
    agent_service = MockAgentService()
    agent_service.add_agent(MockAgent(agent_id))

    # Create a task
    task_id = uuid4()
    task = SimpleTask(
        id=task_id,
        title="Workflow Status Test",
        description="Test workflow status integration",
        query="Test query",
        user_id="test-user",
        agent_id=agent_id,
        status="submitted",  # Initial database status
    )
    task_service.submitted_tasks.append(task)

    # Set workflow status different from database status
    task_service.set_workflow_status(task_id, "completed", {"output": "Workflow completed"})

    auth_context = create_auth_context()

    # Test that get_task_with_workflow_status returns workflow status
    task_with_workflow = await task_service.get_task_with_workflow_status(task_id)
    assert task_with_workflow.status == "completed"  # Should reflect workflow status
    assert task_with_workflow.result == {"output": "Workflow completed"}

    # Test A2A task/get endpoint uses workflow status
    get_params = {"id": str(task_id)}
    response = await handle_task_get(
        request_id="workflow-status-test",
        params=get_params,
        task_service=task_service,
        agent_id=agent_id,
        auth_context=auth_context,
    )

    # Verify response reflects workflow status
    assert response.result is not None
    a2a_task = response.result
    assert a2a_task.status.state.value == "completed"  # Should reflect workflow status

    # Test cancellation with workflow status
    # Set task back to running for cancellation test
    task_service.set_workflow_status(task_id, "running")

    cancel_params = {"id": str(task_id)}
    cancel_response = await handle_task_cancel(
        request_id="workflow-cancel-test",
        params=cancel_params,
        task_service=task_service,
        agent_id=agent_id,
        auth_context=auth_context,
    )

    # Verify successful cancellation
    assert cancel_response.result is not None
    cancelled_task = cancel_response.result
    assert cancelled_task.status.state.value == "canceled"


if __name__ == "__main__":
    # Run specific tests for development
    asyncio.run(test_a2a_task_creation_through_jsonrpc())
    asyncio.run(test_a2a_message_send_creates_temporal_task())
    asyncio.run(test_a2a_task_streaming_with_real_events())
    print("✅ A2A task execution integration tests passed!")
