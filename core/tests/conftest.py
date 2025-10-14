"""Test configuration and fixtures."""

import asyncio
import base64
import json
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import jwt
import pytest
from agentarea_common.auth.context import UserContext


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


# Auth fixtures
@pytest.fixture
def sample_jwks():
    """Sample JWKS for testing."""
    return {
        "keys": [
            {
                "kty": "EC",
                "kid": "test-key-1",
                "use": "sig",
                "alg": "ES256",
                "crv": "P-256",
                "x": "MKBCTNIcKUSDii11ySs3526iDZ8AiTo7Tu6KPAqv7D4",
                "y": "4Etl6SRW2YiLUrN5vfvVHuhp7x8PxltmWWlbbM4IFyM",
                "d": "870MB6gfuTJ4HtUnUvYMyJpr5eUZNP4Bk43bVdj3eAE",
            }
        ]
    }


@pytest.fixture
def jwks_b64(sample_jwks):
    """Base64-encoded JWKS."""
    return base64.b64encode(json.dumps(sample_jwks).encode()).decode()


@pytest.fixture
def test_jwt_secret():
    """Test JWT secret key."""
    return "test-secret-key-for-testing"


@pytest.fixture
def test_user_context():
    """Create test user context."""
    return UserContext(
        user_id="test-user-123", workspace_id="test-workspace-456", roles=["user"]
    )


@pytest.fixture
def test_admin_context():
    """Create test admin user context."""
    return UserContext(
        user_id="admin-user-123", workspace_id="test-workspace-456", roles=["user", "admin"]
    )


def generate_test_jwt_token(
    user_id: str = "test-user",
    workspace_id: str = "test-workspace",
    email: str | None = None,
    roles: list[str] | None = None,
    expires_in_minutes: int = 30,
    secret_key: str = "test-secret-key-for-testing",
    algorithm: str = "HS256",
    issuer: str | None = None,
    audience: str | None = None,
) -> str:
    """Generate a test JWT token.

    Args:
        user_id: User ID for the token
        workspace_id: Workspace ID for the token
        email: Optional email address
        roles: Optional list of roles
        expires_in_minutes: Token expiration in minutes
        secret_key: Secret key for signing
        algorithm: JWT algorithm
        issuer: Optional issuer claim
        audience: Optional audience claim

    Returns:
        JWT token string
    """
    payload = {
        "sub": user_id,
        "workspace_id": workspace_id,
        "iat": datetime.now(UTC),
        "exp": datetime.now(UTC) + timedelta(minutes=expires_in_minutes),
    }

    if email:
        payload["email"] = email
    if roles:
        payload["roles"] = roles
    if issuer:
        payload["iss"] = issuer
    if audience:
        payload["aud"] = audience

    return jwt.encode(payload, secret_key, algorithm=algorithm)


@pytest.fixture
def generate_jwt_token():
    """Fixture that returns the JWT token generation function."""
    return generate_test_jwt_token


@pytest.fixture
def valid_jwt_token(test_jwt_secret):
    """Generate a valid JWT token for testing."""
    return generate_test_jwt_token(
        user_id="test-user-123",
        workspace_id="test-workspace-456",
        email="test@example.com",
        roles=["user"],
        secret_key=test_jwt_secret,
    )


@pytest.fixture
def expired_jwt_token(test_jwt_secret):
    """Generate an expired JWT token for testing."""
    return generate_test_jwt_token(
        user_id="test-user-123",
        workspace_id="test-workspace-456",
        expires_in_minutes=-30,  # Expired 30 minutes ago
        secret_key=test_jwt_secret,
    )


@pytest.fixture
def admin_jwt_token(test_jwt_secret):
    """Generate a JWT token with admin role."""
    return generate_test_jwt_token(
        user_id="admin-user-123",
        workspace_id="test-workspace-456",
        email="admin@example.com",
        roles=["user", "admin"],
        secret_key=test_jwt_secret,
    )


# Pytest configuration
def pytest_configure(config):
    """Configure pytest with custom markers."""
    config.addinivalue_line("markers", "asyncio: mark test as async")
    config.addinivalue_line("markers", "integration: mark test as integration test")
    config.addinivalue_line("markers", "unit: mark test as unit test")
