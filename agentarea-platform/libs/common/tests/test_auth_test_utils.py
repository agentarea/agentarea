"""Unit tests for authentication test utilities."""

import jwt
import pytest
from agentarea_common.auth import UserContext
from agentarea_common.auth.test_utils import (
    create_admin_test_token,
    create_basic_test_token,
    create_expired_test_token,
    create_test_user_context,
    generate_test_jwt_token,
)
from jwt.exceptions import ExpiredSignatureError


class TestGenerateTestJWTToken:
    """Test cases for generate_test_jwt_token function."""

    def test_generate_token_with_all_claims(self, monkeypatch):
        """Test token generation with all possible claims."""
        monkeypatch.setenv("JWT_SECRET_KEY", "test-secret")

        token = generate_test_jwt_token(
            user_id="test-user",
            workspace_id="test-workspace",
            email="test@example.com",
            expires_in_minutes=60,
        )

        # Decode and verify token
        payload = jwt.decode(token, "test-secret", algorithms=["HS256"], audience="agentarea-api")

        assert payload["sub"] == "test-user"
        assert payload["workspace_id"] == "test-workspace"
        assert payload["email"] == "test@example.com"
        assert payload["iss"] == "agentarea-test"
        assert payload["aud"] == "agentarea-api"
        assert "iat" in payload
        assert "exp" in payload

    def test_generate_token_minimal_claims(self, monkeypatch):
        """Test token generation with minimal required claims."""
        monkeypatch.setenv("JWT_SECRET_KEY", "test-secret")

        token = generate_test_jwt_token(user_id="minimal-user", workspace_id="minimal-workspace")

        # Decode and verify token
        payload = jwt.decode(token, "test-secret", algorithms=["HS256"], audience="agentarea-api")

        assert payload["sub"] == "minimal-user"
        assert payload["workspace_id"] == "minimal-workspace"
        assert "email" not in payload  # Should be omitted when None

    def test_generate_token_custom_secret(self):
        """Test token generation with custom secret key."""
        custom_secret = "custom-secret-key"

        token = generate_test_jwt_token(
            user_id="custom-user", workspace_id="custom-workspace", secret_key=custom_secret
        )

        # Verify token can be decoded with custom secret
        payload = jwt.decode(token, custom_secret, algorithms=["HS256"], audience="agentarea-api")
        assert payload["sub"] == "custom-user"
        assert payload["workspace_id"] == "custom-workspace"

    def test_generate_expired_token(self):
        """Test generation of expired token."""
        token = generate_test_jwt_token(
            user_id="expired-user",
            workspace_id="expired-workspace",
            expires_in_minutes=-1,
            secret_key="test-secret",
        )

        # Token should be expired and raise an error when decoded
        with pytest.raises(ExpiredSignatureError):
            jwt.decode(token, "test-secret", algorithms=["HS256"], audience="agentarea-api")


class TestCreateTestUserContext:
    """Test cases for create_test_user_context function."""

    def test_create_context_with_defaults(self):
        """Test creating user context with default values."""
        context = create_test_user_context()

        assert isinstance(context, UserContext)
        assert context.user_id == "test-user-123"
        assert context.workspace_id == "test-workspace-456"

    def test_create_context_with_custom_values(self):
        """Test creating user context with custom values."""
        context = create_test_user_context(user_id="custom-user", workspace_id="custom-workspace")

        assert context.user_id == "custom-user"
        assert context.workspace_id == "custom-workspace"

    def test_create_context_no_email(self):
        """Test creating user context without email."""
        context = create_test_user_context(
            user_id="no-email-user", workspace_id="no-email-workspace"
        )

        assert context.user_id == "no-email-user"
        assert context.workspace_id == "no-email-workspace"
        assert context.email is None


class TestTokenHelpers:
    """Test cases for token helper functions."""

    def test_create_admin_test_token(self, monkeypatch):
        """Test creating admin test token."""
        monkeypatch.setenv("JWT_SECRET_KEY", "test-secret")

        token = create_admin_test_token()

        payload = jwt.decode(token, "test-secret", algorithms=["HS256"], audience="agentarea-api")
        assert payload["sub"] == "admin-user-123"
        assert payload["email"] == "admin@example.com"

    def test_create_basic_test_token(self, monkeypatch):
        """Test creating basic test token."""
        monkeypatch.setenv("JWT_SECRET_KEY", "test-secret")

        token = create_basic_test_token()

        payload = jwt.decode(token, "test-secret", algorithms=["HS256"], audience="agentarea-api")
        assert payload["sub"] == "basic-user-123"
        assert "email" not in payload

    def test_create_expired_test_token(self, monkeypatch):
        """Test creating expired test token."""
        monkeypatch.setenv("JWT_SECRET_KEY", "test-secret")

        token = create_expired_test_token()

        # Token should be expired and raise an error when decoded
        with pytest.raises(ExpiredSignatureError):
            jwt.decode(token, "test-secret", algorithms=["HS256"], audience="agentarea-api")
