"""Test utilities for JWT token generation and authentication testing."""

from datetime import UTC, datetime, timedelta

import jwt

from ..config.settings import get_settings
from .context import UserContext


def generate_test_jwt_token(
    user_id: str,
    workspace_id: str,
    email: str | None = None,
    roles: list[str] | None = None,
    expires_in_minutes: int = 30,
    secret_key: str | None = None,
    algorithm: str = "HS256",
) -> str:
    """Generate a test JWT token for development and testing.

    Args:
        user_id: User identifier
        workspace_id: Workspace identifier
        email: Optional user email
        roles: Optional list of user roles
        expires_in_minutes: Token expiration time in minutes
        secret_key: Optional secret key (uses app settings if not provided)
        algorithm: JWT algorithm to use

    Returns:
        str: Encoded JWT token
    """
    if roles is None:
        roles = ["user"]

    if secret_key is None:
        settings = get_settings()
        secret_key = settings.app.JWT_SECRET_KEY

    # Create token payload
    now = datetime.now(UTC)
    payload = {
        "sub": user_id,
        "workspace_id": workspace_id,
        "email": email,
        "roles": roles,
        "iat": now,
        "exp": now + timedelta(minutes=expires_in_minutes),
        "iss": "agentarea-test",
        "aud": "agentarea-api",
    }

    # Remove None values
    payload = {k: v for k, v in payload.items() if v is not None}

    return jwt.encode(payload, secret_key, algorithm=algorithm)


def create_test_user_context(
    user_id: str = "test-user-123",
    workspace_id: str = "test-workspace-456",
    roles: list[str] | None = None,
) -> UserContext:
    """Create a test UserContext for testing purposes.

    Args:
        user_id: User identifier
        workspace_id: Workspace identifier
        roles: Optional list of user roles

    Returns:
        UserContext: Test user context
    """
    if roles is None:
        roles = ["user"]

    return UserContext(user_id=user_id, workspace_id=workspace_id, roles=roles)


def create_admin_test_token(
    user_id: str = "admin-user-123",
    workspace_id: str = "admin-workspace-456",
    email: str = "admin@example.com",
) -> str:
    """Create a test JWT token with admin privileges.

    Args:
        user_id: Admin user identifier
        workspace_id: Workspace identifier
        email: Admin user email

    Returns:
        str: JWT token with admin role
    """
    return generate_test_jwt_token(
        user_id=user_id, workspace_id=workspace_id, email=email, roles=["user", "admin"]
    )


def create_basic_test_token(
    user_id: str = "basic-user-123", workspace_id: str = "basic-workspace-456"
) -> str:
    """Create a basic test JWT token with minimal claims.

    Args:
        user_id: User identifier
        workspace_id: Workspace identifier

    Returns:
        str: JWT token with basic user role
    """
    return generate_test_jwt_token(user_id=user_id, workspace_id=workspace_id, roles=["user"])


def create_expired_test_token(
    user_id: str = "expired-user-123", workspace_id: str = "expired-workspace-456"
) -> str:
    """Create an expired test JWT token for testing error handling.

    Args:
        user_id: User identifier
        workspace_id: Workspace identifier

    Returns:
        str: Expired JWT token
    """
    return generate_test_jwt_token(
        user_id=user_id,
        workspace_id=workspace_id,
        expires_in_minutes=-1,  # Already expired
    )
