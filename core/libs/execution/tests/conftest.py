"""Pytest configuration and fixtures for AgentArea execution tests."""

import asyncio
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from agentarea_execution.models import AgentExecutionRequest


class MockActivityServices:
    """Mock activity services for testing."""

    def __init__(self):
        self.agent_service = AsyncMock()
        self.mcp_service = AsyncMock()
        self.llm_service = AsyncMock()
        self.event_broker = AsyncMock()

        # Configure default return values
        self.agent_service.build_agent_config.return_value = {
            "name": "test_agent",
            "description": "Test agent",
            "instruction": "You are a helpful assistant",
            "model_instance": {
                "model_name": "gemini-2.0-flash",
                "provider": "google",
            },
            "tools_config": {
                "mcp_servers": [],
            },
        }

        self.agent_service.update_agent_memory.return_value = {"memory_entries_created": 2}

        self.mcp_service.get_server_instance.return_value = None
        self.mcp_service.get_server_tools.return_value = []

        self.event_broker.publish_event.return_value = None


@pytest.fixture
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def mock_services():
    """Fixture providing mock services."""
    return MockActivityServices()


@pytest.fixture
def sample_request():
    """Fixture providing a sample execution request."""
    return AgentExecutionRequest(
        task_id=uuid4(),
        agent_id=uuid4(),
        user_id="test_user",
        task_query="What is the weather in New York?",
        max_reasoning_iterations=5,
        timeout_seconds=300,
    )


@pytest.fixture
def multi_agent_request():
    """Fixture for multi-agent execution request."""
    return AgentExecutionRequest(
        task_id=uuid4(),
        agent_id=uuid4(),
        user_id="test_user",
        task_query="Research the weather in New York, then have another agent analyze the implications for tourism.",
        max_reasoning_iterations=10,
        timeout_seconds=600,
    )
