"""Test utilities for JWT token generation and authentication testing."""

import os
from datetime import UTC, datetime, timedelta

import jwt

from agentarea_common.auth.context import UserContext

# Default secret used when no explicit key and no JWT_SECRET_KEY env var is set.
# These helpers are test-only — they intentionally avoid pulling the full app
# Settings cluster (which depends on Temporal/Workflow env vars and would force
# every JWT-helper caller to bootstrap unrelated configuration).
_DEFAULT_TEST_JWT_SECRET = "agentarea-test-secret-key-not-for-prod"  # noqa: S105


def generate_test_jwt_token(
    user_id: str,
    workspace_id: str,
    email: str | None = None,
    expires_in_minutes: int = 30,
    secret_key: str | None = None,
    algorithm: str = "HS256",
) -> str:
    """Generate a test JWT token for development and testing."""
    if secret_key is None:
        secret_key = os.environ.get("JWT_SECRET_KEY", _DEFAULT_TEST_JWT_SECRET)

    now = datetime.now(UTC)
    payload = {
        "sub": user_id,
        "workspace_id": workspace_id,
        "email": email,
        "iat": now,
        "exp": now + timedelta(minutes=expires_in_minutes),
        "iss": "agentarea-test",
        "aud": "agentarea-api",
    }

    payload = {k: v for k, v in payload.items() if v is not None}

    return jwt.encode(payload, secret_key, algorithm=algorithm)


def create_test_user_context(
    user_id: str = "test-user-123",
    workspace_id: str = "test-workspace-456",
) -> UserContext:
    """Create a test UserContext for testing purposes."""
    return UserContext(user_id=user_id, workspace_id=workspace_id)


def create_admin_test_token(
    user_id: str = "admin-user-123",
    workspace_id: str = "admin-workspace-456",
    email: str = "admin@example.com",
) -> str:
    """Create a test JWT token."""
    return generate_test_jwt_token(user_id=user_id, workspace_id=workspace_id, email=email)


def create_basic_test_token(
    user_id: str = "basic-user-123", workspace_id: str = "basic-workspace-456"
) -> str:
    """Create a basic test JWT token."""
    return generate_test_jwt_token(user_id=user_id, workspace_id=workspace_id)


def create_expired_test_token(
    user_id: str = "expired-user-123", workspace_id: str = "expired-workspace-456"
) -> str:
    """Create an expired test JWT token for testing error handling."""
    return generate_test_jwt_token(
        user_id=user_id,
        workspace_id=workspace_id,
        expires_in_minutes=-1,
    )
