"""Pytest configuration and fixtures for AgentArea context tests."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from agentarea_common.auth import UserContext
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def mock_db_session():
    """Mock database session for testing."""
    session = AsyncMock(spec=AsyncSession)
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.add = MagicMock()
    session.delete = AsyncMock()
    return session


@pytest.fixture
def test_user_context():
    """Test user context for workspace scoping."""
    return UserContext(
        user_id="test-user-123",
        workspace_id="test-workspace-456",
    )


@pytest.fixture
def test_admin_context():
    """Test admin user context."""
    return UserContext(
        user_id="admin-user-123",
        workspace_id="test-workspace-456",
        roles=["user", "admin"],
    )
