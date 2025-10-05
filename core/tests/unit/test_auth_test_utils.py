"""Unit tests for authentication test utilities."""

from unittest.mock import Mock, patch

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

    @patch("agentarea_common.auth.test_utils.get_settings")
    def test_generate_token_with_all_claims(self, mock_get_settings):
        """Test token generation with all possible claims."""
        # Setup settings mock
        mock_settings = Mock()
        mock_settings.app.JWT_SECRET_KEY = "test-secret"
        mock_get_settings.return_value = mock_settings

        token = generate_test_jwt_token(
            user_id="test-user",
            workspace_id="test-workspace",
            email="test@example.com",
            roles=["user", "admin"],
            expires_in_minutes=60,
        )

        # Decode and verify token
        payload = jwt.decode(token, "test-secret", algorithms=["HS256"], audience="agentarea-api")

        assert payload["sub"] == "test-user"
        assert payload["workspace_id"] == "test-workspace"
        assert payload["email"] == "test@example.com"
        assert payload["roles"] == ["user", "admin"]
        assert payload["iss"] == "agentarea-test"
        assert payload["aud"] == "agentarea-api"
        assert "iat" in payload
        assert "exp" in payload

    @patch("agentarea_common.auth.test_utils.get_settings")
    def test_generate_token_minimal_claims(self, mock_get_settings):
        """Test token generation with minimal required claims."""
        # Setup settings mock
        mock_settings = Mock()
        mock_settings.app.JWT_SECRET_KEY = "test-secret"
        mock_get_settings.return_value = mock_settings

        token = generate_test_jwt_token(user_id="minimal-user", workspace_id="minimal-workspace")

        # Decode and verify token
        payload = jwt.decode(token, "test-secret", algorithms=["HS256"], audience="agentarea-api")

        assert payload["sub"] == "minimal-user"
        assert payload["workspace_id"] == "minimal-workspace"
        assert payload["roles"] == ["user"]  # Default role
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
        assert context.roles == ["user"]

    def test_create_context_with_custom_values(self):
        """Test creating user context with custom values."""
        context = create_test_user_context(
            user_id="custom-user", workspace_id="custom-workspace", roles=["admin", "developer"]
        )

        assert context.user_id == "custom-user"
        assert context.workspace_id == "custom-workspace"
        assert context.roles == ["admin", "developer"]

    def test_create_context_no_email(self):
        """Test creating user context without email."""
        context = create_test_user_context(
            user_id="no-email-user", workspace_id="no-email-workspace"
        )

        assert context.user_id == "no-email-user"
        assert context.workspace_id == "no-email-workspace"
        assert context.roles == ["user"]


class TestTokenHelpers:
    """Test cases for token helper functions."""

    @patch("agentarea_common.auth.test_utils.get_settings")
    def test_create_admin_test_token(self, mock_get_settings):
        """Test creating admin test token."""
        # Setup settings mock
        mock_settings = Mock()
        mock_settings.app.JWT_SECRET_KEY = "test-secret"
        mock_get_settings.return_value = mock_settings

        token = create_admin_test_token()

        # Decode and verify token has admin role
        payload = jwt.decode(token, "test-secret", algorithms=["HS256"], audience="agentarea-api")
        assert "admin" in payload["roles"]
        assert "user" in payload["roles"]
        assert payload["email"] == "admin@example.com"

    @patch("agentarea_common.auth.test_utils.get_settings")
    def test_create_basic_test_token(self, mock_get_settings):
        """Test creating basic test token."""
        # Setup settings mock
        mock_settings = Mock()
        mock_settings.app.JWT_SECRET_KEY = "test-secret"
        mock_get_settings.return_value = mock_settings

        token = create_basic_test_token()

        # Decode and verify token has only user role
        payload = jwt.decode(token, "test-secret", algorithms=["HS256"], audience="agentarea-api")
        assert payload["roles"] == ["user"]
        assert "email" not in payload

    @patch("agentarea_common.auth.test_utils.get_settings")
    def test_create_expired_test_token(self, mock_get_settings):
        """Test creating expired test token."""
        # Setup settings mock
        mock_settings = Mock()
        mock_settings.app.JWT_SECRET_KEY = "test-secret"
        mock_get_settings.return_value = mock_settings

        token = create_expired_test_token()

        # Token should be expired and raise an error when decoded
        with pytest.raises(ExpiredSignatureError):
            jwt.decode(token, "test-secret", algorithms=["HS256"], audience="agentarea-api")
