"""Test configuration and fixtures."""

import asyncio
import base64
import json
import os
import shutil
import tempfile
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import jwt
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


# Auth fixtures
def generate_es256_jwk(kid: str = "test-key-1") -> dict:
    """Build a throwaway ES256 JWK, including its private component.

    Generated per run rather than hardcoded: a committed private key trips secret
    scanners and invites reuse outside tests, which is how one key ended up
    signing tokens on every self-hosted install.
    """
    from cryptography.hazmat.primitives.asymmetric import ec

    def b64(value: int) -> str:
        return base64.urlsafe_b64encode(value.to_bytes(32, "big")).decode().rstrip("=")

    key = ec.generate_private_key(ec.SECP256R1())
    public = key.public_key().public_numbers()
    return {
        "kty": "EC",
        "kid": kid,
        "use": "sig",
        "alg": "ES256",
        "crv": "P-256",
        "x": b64(public.x),
        "y": b64(public.y),
        "d": b64(key.private_numbers().private_value),
    }


@pytest.fixture
def sample_jwks():
    """Sample JWKS for testing."""
    return {"keys": [generate_es256_jwk()]}


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
    from agentarea_common.auth.context import UserContext

    return UserContext(user_id="test-user-123", workspace_id="test-workspace-456")


@pytest.fixture
def test_admin_context():
    """Create test admin user context."""
    from agentarea_common.auth.context import UserContext

    return UserContext(user_id="admin-user-123", workspace_id="test-workspace-456")


def generate_test_jwt_token(
    user_id: str = "test-user",
    workspace_id: str = "test-workspace",
    email: str | None = None,
    expires_in_minutes: int = 30,
    secret_key: str = "test-secret-key-for-testing",  # noqa: S107
    algorithm: str = "HS256",
    issuer: str | None = None,
    audience: str | None = None,
) -> str:
    """Generate a test JWT token."""
    payload = {
        "sub": user_id,
        "workspace_id": workspace_id,
        "iat": datetime.now(UTC),
        "exp": datetime.now(UTC) + timedelta(minutes=expires_in_minutes),
    }

    if email:
        payload["email"] = email
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
        secret_key=test_jwt_secret,
    )


def _patch_temporal_test_server_startup() -> None:
    """Make Temporal test-server downloads resilient in CI."""
    try:
        from temporalio.testing import WorkflowEnvironment
    except ImportError:
        return

    if getattr(WorkflowEnvironment, "_agentarea_test_server_patch", False):
        return

    original_start_time_skipping = WorkflowEnvironment.start_time_skipping

    async def start_time_skipping_with_retry(cls, **kwargs):
        download_dir = os.environ.get("TEMPORAL_TEST_SERVER_DOWNLOAD_DIR")
        if not download_dir:
            download_dir = os.path.join(tempfile.gettempdir(), "agentarea-temporal-test-server")
        os.makedirs(download_dir, exist_ok=True)
        kwargs.setdefault("download_dest_dir", download_dir)

        attempts = int(os.environ.get("TEMPORAL_TEST_SERVER_DOWNLOAD_ATTEMPTS", "4"))
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                return await original_start_time_skipping(**kwargs)
            except Exception as exc:
                last_error = exc
                if attempt == attempts:
                    break
                shutil.rmtree(download_dir, ignore_errors=True)
                await asyncio.sleep(min(2**attempt, 10))
        if last_error is None:
            raise RuntimeError("Temporal test server did not start")
        raise last_error

    WorkflowEnvironment.start_time_skipping = classmethod(start_time_skipping_with_retry)
    WorkflowEnvironment._agentarea_test_server_patch = True


def pytest_configure(config):
    """Configure pytest with custom markers and environment variables."""
    _patch_temporal_test_server_startup()

    # Set required environment variables for WorkflowSettings
    os.environ.setdefault("WORKFLOW__TEMPORAL_SERVER_URL", "localhost:7233")
    os.environ.setdefault("WORKFLOW__TEMPORAL_NAMESPACE", "default")
    os.environ.setdefault("WORKFLOW__TEMPORAL_TASK_QUEUE", "agent-tasks")

    # Set required Kratos settings for auth
    os.environ.setdefault("KRATOS_ISSUER", "http://localhost:4433")
    os.environ.setdefault("KRATOS_AUDIENCE", "agentarea")
    os.environ.setdefault(
        "KRATOS_JWKS_B64", base64.b64encode(json.dumps({"keys": []}).encode()).decode()
    )

    config.addinivalue_line("markers", "asyncio: mark test as async")
    config.addinivalue_line("markers", "integration: mark test as integration test")
    config.addinivalue_line("markers", "unit: mark test as unit test")
    config.addinivalue_line(
        "markers", "flow(name): canonical main-flow test (agentarea_common.testing.flows)"
    )


def pytest_collection_modifyitems(config, items):
    """Record which main flows are exercised, for the flow-registry guard."""
    from agentarea_common.testing.flows import COVERED_FLOWS

    for item in items:
        for marker in item.iter_markers(name="flow"):
            if marker.args:
                flow = marker.args[0]
                COVERED_FLOWS.add(getattr(flow, "value", flow))


# SQLite-backed Temporal server fixtures (see module docstring for when to use).
# Register cross-dialect compilation shims (JSONB/INET -> SQLite) so tests that
# create the schema on in-memory SQLite don't fail on Postgres-only column types.
from agentarea_common.testing import sqlite_compat  # noqa: E402, F401
from agentarea_common.testing.temporal import (  # noqa: E402, F401
    temporal_sqlite_client,
    temporal_sqlite_env,
)
