"""Test configuration and fixtures."""

import asyncio
from unittest.mock import MagicMock

import pytest


# Configure asyncio for pytest
@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


# Mock fixtures for common dependencies
@pytest.fixture
def mock_event_broker():
    """Mock event broker for testing."""
    broker = MagicMock()
    broker.publish = MagicMock()
    return broker


@pytest.fixture
def mock_secret_manager():
    """Mock secret manager for testing."""
    manager = MagicMock()
    manager.get_secret = MagicMock(return_value="mock-api-key")
    return manager


@pytest.fixture
def mock_repository_factory():
    """Mock repository factory for testing."""
    factory = MagicMock()
    return factory


# Test database configuration
@pytest.fixture
def test_database_url():
    """Test database URL."""
    return "postgresql+asyncpg://test:test@localhost:5432/test_agentarea"


# Pytest configuration
def pytest_configure(config):
    """Configure pytest with custom markers."""
    config.addinivalue_line(
        "markers", "asyncio: mark test as async"
    )
    config.addinivalue_line(
        "markers", "integration: mark test as integration test"
    )
    config.addinivalue_line(
        "markers", "unit: mark test as unit test"
    )
