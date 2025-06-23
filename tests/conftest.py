"""
Global pytest configuration and fixtures
========================================

Shared fixtures and configuration for all tests.
"""

import pytest
import asyncio
from typing import AsyncGenerator
from uuid import uuid4
import os
import sys

# Add the core directory to Python path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    policy = asyncio.get_event_loop_policy()
    loop = policy.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def sample_agent_id():
    """Generate a sample agent ID for testing"""
    return uuid4()


@pytest.fixture
def sample_user_id():
    """Generate a sample user ID for testing"""
    return "test_user_123"


@pytest.fixture
def sample_task_id():
    """Generate a sample task ID for testing"""
    return f"task_{uuid4()}"


@pytest.fixture
def mock_ollama_config():
    """Mock Ollama configuration"""
    return {
        "model": "ollama_chat/qwen2.5",
        "base_url": "http://localhost:11434",
        "timeout": 30.0,
    }


@pytest.fixture
def mock_agent_config():
    """Mock agent configuration"""
    return {
        "id": str(uuid4()),
        "name": "Test Agent",
        "description": "Test agent for unit tests",
        "instruction": "You are a helpful test assistant",
        "planning_enabled": False,
        "workflow_type": "single",
        "tools_config": {"mcp_servers": [], "builtin_tools": [], "custom_tools": []},
    }


# Integration test markers
pytest_plugins = []


def pytest_configure(config):
    """Configure pytest with custom markers"""
    config.addinivalue_line(
        "markers", "integration: mark test as integration test requiring real services"
    )
    config.addinivalue_line("markers", "slow: mark test as slow running")
    config.addinivalue_line("markers", "unit: mark test as unit test (isolated)")


def pytest_collection_modifyitems(config, items):
    """Modify collected test items to add markers based on file location"""
    for item in items:
        # Add marker based on test file location
        if "integration" in str(item.fspath):
            item.add_marker(pytest.mark.integration)
        elif "unit" in str(item.fspath):
            item.add_marker(pytest.mark.unit)

        # Mark slow tests
        if "slow" in item.name.lower():
            item.add_marker(pytest.mark.slow)
