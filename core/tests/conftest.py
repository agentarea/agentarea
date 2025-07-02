"""
Global pytest configuration and fixtures
========================================

Shared fixtures and configuration for all tests.
"""

import asyncio
import os
import sys
from uuid import uuid4

import pytest

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
def test_redis_available():
    """Check if Redis is available for tests."""
    try:
        import redis
        r = redis.Redis.from_url("redis://localhost:6379")
        r.ping()
        return True
    except (ImportError, redis.ConnectionError, redis.TimeoutError):
        pytest.skip("Redis not available for testing")


@pytest.fixture
def test_postgres_available():
    """Check if PostgreSQL is available for tests."""
    try:
        import asyncpg
        import asyncio
        
        async def check_postgres():
            try:
                conn = await asyncpg.connect(
                    host="localhost",
                    port=5432,
                    user="postgres",
                    password="postgres",
                    database="aiagents"
                )
                await conn.close()
                return True
            except Exception:
                return False
        
        if not asyncio.run(check_postgres()):
            pytest.skip("PostgreSQL not available for testing")
    except ImportError:
        pytest.skip("asyncpg not available for testing")


@pytest.fixture
def test_temporal_available():
    """Check if Temporal is available for tests."""
    import socket
    
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex(("localhost", 7233))
        sock.close()
        if result != 0:
            pytest.skip("Temporal not available for testing")
    except Exception:
        pytest.skip("Temporal not available for testing")


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
