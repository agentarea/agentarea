"""Unit tests for authentication dependencies."""

from unittest.mock import Mock, patch

import jwt
import pytest
from agentarea_common.auth import UserContext, get_user_context
from agentarea_common.auth.context_manager import ContextManager
from agentarea_common.auth.jwt_handler import JWTTokenHandler
from fastapi import HTTPException, Request


class TestJWTTokenHandler:
    """Test cases for JWTTokenHandler."""

    @pytest.fixture
    def jwt_handler(self):
        """Create JWT handler for testing."""
        return JWTTokenHandler(secret_key="test-secret", algorithm="HS256")

    @pytest.fixture
    def mock_request(self):
        """Create mock request object."""
        request = Mock(spec=Request)
        request.headers = {}
        return request

    def test_extract_token_from_header_success(self, jwt_handler, mock_request):
        """Test successful token extraction from Authorization header."""
        mock_request.headers = {"authorization": "Bearer test-token"}

        token = jwt_handler._extract_token_from_header(mock_request)

        assert token == "test-token"

    def test_extract_token_from_header_no_header(self, jwt_handler, mock_request):
        """Test token extraction when no Authorization header present."""
        mock_request.headers = {}

        token = jwt_handler._extract_token_from_header(mock_request)

        assert token is None

    def test_extract_token_from_header_wrong_scheme(self, jwt_handler, mock_request):
        """Test token extraction with wrong authentication scheme."""
        mock_request.headers = {"authorization": "Basic test-token"}

        token = jwt_handler._extract_token_from_header(mock_request)

        assert token is None

    @pytest.mark.asyncio
    async def test_extract_user_context_success(self, jwt_handler, mock_request):
        """Test successful user context extraction from valid JWT."""
        # Create a valid JWT token
        payload = {
            "sub": "test-user-123",
            "workspace_id": "test-workspace-456",
            "email": "test@example.com",
            "roles": ["user", "admin"],
        }
        token = jwt.encode(payload, "test-secret", algorithm="HS256")
        mock_request.headers = {"authorization": f"Bearer {token}"}

        context = await jwt_handler.extract_user_context(mock_request)

        assert isinstance(context, UserContext)
        assert context.user_id == "test-user-123"
        assert context.workspace_id == "test-workspace-456"
        assert context.email == "test@example.com"
        assert context.roles == ["user", "admin"]

    @pytest.mark.asyncio
    async def test_extract_user_context_missing_token(self, jwt_handler, mock_request):
        """Test user context extraction when token is missing."""
        mock_request.headers = {}

        with pytest.raises(HTTPException) as exc_info:
            await jwt_handler.extract_user_context(mock_request)

        assert exc_info.value.status_code == 401
        assert "Missing authorization token" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_extract_user_context_invalid_token(self, jwt_handler, mock_request):
        """Test user context extraction with invalid JWT token."""
        mock_request.headers = {"authorization": "Bearer invalid-token"}

        with pytest.raises(HTTPException) as exc_info:
            await jwt_handler.extract_user_context(mock_request)

        assert exc_info.value.status_code == 401
        assert "Invalid token" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_extract_user_context_missing_sub_claim(self, jwt_handler, mock_request):
        """Test user context extraction when 'sub' claim is missing."""
        payload = {"workspace_id": "test-workspace-456", "email": "test@example.com"}
        token = jwt.encode(payload, "test-secret", algorithm="HS256")
        mock_request.headers = {"authorization": f"Bearer {token}"}

        with pytest.raises(HTTPException) as exc_info:
            await jwt_handler.extract_user_context(mock_request)

        assert exc_info.value.status_code == 400
        assert "Token missing required 'sub' claim" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_extract_user_context_missing_workspace_claim(self, jwt_handler, mock_request):
        """Test user context extraction when 'workspace_id' claim is missing."""
        payload = {"sub": "test-user-123", "email": "test@example.com"}
        token = jwt.encode(payload, "test-secret", algorithm="HS256")
        mock_request.headers = {"authorization": f"Bearer {token}"}

        with pytest.raises(HTTPException) as exc_info:
            await jwt_handler.extract_user_context(mock_request)

        assert exc_info.value.status_code == 400
        assert "Token missing required 'workspace_id' claim" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_extract_user_context_minimal_claims(self, jwt_handler, mock_request):
        """Test user context extraction with minimal required claims."""
        payload = {"sub": "test-user-123", "workspace_id": "test-workspace-456"}
        token = jwt.encode(payload, "test-secret", algorithm="HS256")
        mock_request.headers = {"authorization": f"Bearer {token}"}

        context = await jwt_handler.extract_user_context(mock_request)

        assert context.user_id == "test-user-123"
        assert context.workspace_id == "test-workspace-456"
        assert context.email is None
        assert context.roles == []  # Default empty list


class TestGetUserContext:
    """Test cases for get_user_context dependency function."""

    @pytest.fixture
    def mock_request(self):
        """Create mock request object."""
        request = Mock(spec=Request)
        request.headers = {}
        return request

    @pytest.mark.asyncio
    @patch("agentarea_common.auth.dependencies.get_jwt_handler")
    @patch("agentarea_common.auth.dependencies.ContextManager")
    async def test_get_user_context_success(
        self, mock_context_manager, mock_get_jwt_handler, mock_request
    ):
        """Test successful user context extraction and context manager setting."""
        # Setup mocks
        mock_jwt_handler = Mock()
        mock_get_jwt_handler.return_value = mock_jwt_handler

        expected_context = UserContext(
            user_id="test-user",
            workspace_id="test-workspace",
            email="test@example.com",
            roles=["user"],
        )

        # Make the extract_user_context method async
        async def mock_extract_user_context(request):
            return expected_context

        mock_jwt_handler.extract_user_context = mock_extract_user_context

        # Call the dependency
        result = await get_user_context(mock_request)

        # Verify results
        assert result == expected_context
        mock_context_manager.set_context.assert_called_once_with(expected_context)

    @pytest.mark.asyncio
    @patch("agentarea_common.auth.dependencies.get_jwt_handler")
    async def test_get_user_context_jwt_error_propagation(self, mock_get_jwt_handler, mock_request):
        """Test that JWT errors are properly propagated."""
        # Setup mocks
        mock_jwt_handler = Mock()
        mock_get_jwt_handler.return_value = mock_jwt_handler

        expected_exception = HTTPException(status_code=401, detail="Invalid token")
        mock_jwt_handler.extract_user_context.side_effect = expected_exception

        # Call the dependency and verify exception is raised
        with pytest.raises(HTTPException) as exc_info:
            await get_user_context(mock_request)

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Invalid token"


class TestIntegration:
    """Integration tests for the complete authentication flow."""

    @pytest.mark.asyncio
    @patch("agentarea_common.auth.jwt_handler.get_settings")
    async def test_end_to_end_authentication_flow(self, mock_get_settings):
        """Test the complete authentication flow from request to context."""
        # Setup settings mock
        mock_settings = Mock()
        mock_settings.app.JWT_SECRET_KEY = "test-secret-key"
        mock_settings.app.JWT_ALGORITHM = "HS256"
        mock_get_settings.return_value = mock_settings

        # Create a valid JWT token
        payload = {
            "sub": "integration-user-123",
            "workspace_id": "integration-workspace-456",
            "email": "integration@example.com",
            "roles": ["user", "developer"],
        }
        token = jwt.encode(payload, "test-secret-key", algorithm="HS256")

        # Create mock request with token
        mock_request = Mock(spec=Request)
        mock_request.headers = {"authorization": f"Bearer {token}"}

        # Clear any existing context
        ContextManager.clear_context()

        # Call the dependency
        result = await get_user_context(mock_request)

        # Verify the result
        assert isinstance(result, UserContext)
        assert result.user_id == "integration-user-123"
        assert result.workspace_id == "integration-workspace-456"
        assert result.email == "integration@example.com"
        assert result.roles == ["user", "developer"]

        # Verify context was set in ContextManager
        context_from_manager = ContextManager.get_context()
        assert context_from_manager == result
        assert context_from_manager.user_id == "integration-user-123"
        assert context_from_manager.workspace_id == "integration-workspace-456"

    @pytest.mark.asyncio
    @patch("agentarea_common.auth.jwt_handler.get_settings")
    async def test_context_isolation_between_requests(self, mock_get_settings):
        """Test that context is properly isolated between different requests."""
        # Setup settings mock
        mock_settings = Mock()
        mock_settings.app.JWT_SECRET_KEY = "test-secret-key"
        mock_settings.app.JWT_ALGORITHM = "HS256"
        mock_get_settings.return_value = mock_settings

        # First request
        payload1 = {"sub": "user-1", "workspace_id": "workspace-1"}
        token1 = jwt.encode(payload1, "test-secret-key", algorithm="HS256")
        mock_request1 = Mock(spec=Request)
        mock_request1.headers = {"authorization": f"Bearer {token1}"}

        result1 = await get_user_context(mock_request1)
        assert result1.user_id == "user-1"
        assert result1.workspace_id == "workspace-1"

        # Second request (simulating different context)
        payload2 = {"sub": "user-2", "workspace_id": "workspace-2"}
        token2 = jwt.encode(payload2, "test-secret-key", algorithm="HS256")
        mock_request2 = Mock(spec=Request)
        mock_request2.headers = {"authorization": f"Bearer {token2}"}

        result2 = await get_user_context(mock_request2)
        assert result2.user_id == "user-2"
        assert result2.workspace_id == "workspace-2"

        # Verify context manager has the latest context
        current_context = ContextManager.get_context()
        assert current_context.user_id == "user-2"
        assert current_context.workspace_id == "workspace-2"
