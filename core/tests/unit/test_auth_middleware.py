"""Unit tests for authentication middleware."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from agentarea_common.auth.context_manager import ContextManager
from agentarea_common.auth.interfaces import AuthResult, AuthToken
from agentarea_common.auth.middleware import AuthMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


class TestAuthMiddleware:
    """Test suite for AuthMiddleware."""

    @pytest.fixture
    def mock_app(self):
        """Mock FastAPI application."""
        return MagicMock()

    @pytest.fixture
    def mock_auth_provider(self):
        """Mock authentication provider."""
        provider = AsyncMock()
        provider.verify_token = AsyncMock()
        return provider

    @pytest.fixture
    def middleware(self, mock_app, mock_auth_provider):
        """Create middleware instance."""
        with patch(
            "agentarea_common.auth.middleware.AuthProviderFactory.create_provider",
            return_value=mock_auth_provider,
        ):
            middleware = AuthMiddleware(mock_app, provider_name="kratos")
            return middleware

    @pytest.fixture
    def mock_request(self):
        """Create mock request."""
        request = MagicMock(spec=Request)
        request.headers = {}
        request.url = MagicMock()
        return request

    @pytest.fixture
    def mock_call_next(self):
        """Create mock call_next function."""
        async def call_next(request):
            response = MagicMock()
            response.status_code = 200
            return response

        return AsyncMock(side_effect=call_next)

    def test_middleware_initialization(self, mock_app):
        """Test middleware initialization."""
        with patch("agentarea_common.auth.middleware.AuthProviderFactory.create_provider"):
            middleware = AuthMiddleware(mock_app, provider_name="kratos", config={})
            assert middleware is not None

    @pytest.mark.asyncio
    async def test_public_route_root(self, middleware, mock_request, mock_call_next):
        """Test that root route is public."""
        mock_request.url.path = "/"

        response = await middleware.dispatch(mock_request, mock_call_next)

        mock_call_next.assert_called_once()
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_public_route_health(self, middleware, mock_request, mock_call_next):
        """Test that /health route is public."""
        mock_request.url.path = "/health"

        response = await middleware.dispatch(mock_request, mock_call_next)

        mock_call_next.assert_called_once()
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_public_route_docs(self, middleware, mock_request, mock_call_next):
        """Test that /docs route is public."""
        mock_request.url.path = "/docs"

        response = await middleware.dispatch(mock_request, mock_call_next)

        mock_call_next.assert_called_once()
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_public_route_openapi(self, middleware, mock_request, mock_call_next):
        """Test that /openapi.json route is public."""
        mock_request.url.path = "/openapi.json"

        response = await middleware.dispatch(mock_request, mock_call_next)

        mock_call_next.assert_called_once()
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_public_route_auth_prefix(self, middleware, mock_request, mock_call_next):
        """Test that /v1/auth/* routes are public."""
        mock_request.url.path = "/v1/auth/users/me"

        response = await middleware.dispatch(mock_request, mock_call_next)

        mock_call_next.assert_called_once()
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_public_route_a2a_wellknown(self, middleware, mock_request, mock_call_next):
        """Test that A2A well-known route is public."""
        mock_request.url.path = "/a2a/well-known"

        response = await middleware.dispatch(mock_request, mock_call_next)

        mock_call_next.assert_called_once()
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_public_route_a2a_rpc(self, middleware, mock_request, mock_call_next):
        """Test that A2A RPC route is public."""
        mock_request.url.path = "/a2a/rpc/invoke"

        response = await middleware.dispatch(mock_request, mock_call_next)

        mock_call_next.assert_called_once()
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_protected_route_missing_auth_header(
        self, middleware, mock_request, mock_call_next
    ):
        """Test that protected routes return 401 when auth header is missing."""
        mock_request.url.path = "/v1/agents"
        mock_request.headers = {}

        response = await middleware.dispatch(mock_request, mock_call_next)

        mock_call_next.assert_not_called()
        assert isinstance(response, JSONResponse)
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_protected_route_invalid_auth_header(
        self, middleware, mock_request, mock_call_next
    ):
        """Test that protected routes return 401 for invalid auth header format."""
        mock_request.url.path = "/v1/agents"
        mock_request.headers = {"Authorization": "InvalidFormat token"}

        response = await middleware.dispatch(mock_request, mock_call_next)

        mock_call_next.assert_not_called()
        assert isinstance(response, JSONResponse)
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_protected_route_valid_token(self, middleware, mock_request, mock_call_next):
        """Test that protected routes work with valid token."""
        mock_request.url.path = "/v1/agents"
        mock_request.headers = {
            "Authorization": "Bearer valid-token",
            "X-Workspace-ID": "workspace-123",
        }

        # Mock successful authentication
        auth_token = AuthToken(user_id="user-123", email="test@example.com")
        auth_result = AuthResult(
            is_authenticated=True, user_id="user-123", token=auth_token, error=None
        )
        middleware.auth_provider.verify_token.return_value = auth_result

        response = await middleware.dispatch(mock_request, mock_call_next)

        middleware.auth_provider.verify_token.assert_called_once_with("valid-token")
        mock_call_next.assert_called_once()
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_protected_route_invalid_token(
        self, middleware, mock_request, mock_call_next
    ):
        """Test that protected routes return 401 for invalid token."""
        mock_request.url.path = "/v1/agents"
        mock_request.headers = {"Authorization": "Bearer invalid-token"}

        # Mock failed authentication
        auth_result = AuthResult(
            is_authenticated=False, user_id=None, token=None, error="Invalid token"
        )
        middleware.auth_provider.verify_token.return_value = auth_result

        response = await middleware.dispatch(mock_request, mock_call_next)

        middleware.auth_provider.verify_token.assert_called_once_with("invalid-token")
        mock_call_next.assert_not_called()
        assert isinstance(response, JSONResponse)
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_workspace_id_from_header(self, middleware, mock_request, mock_call_next):
        """Test that workspace ID is extracted from header."""
        mock_request.url.path = "/v1/agents"
        mock_request.headers = {
            "Authorization": "Bearer valid-token",
            "X-Workspace-ID": "custom-workspace",
        }

        # Mock successful authentication
        auth_token = AuthToken(user_id="user-123", email="test@example.com")
        auth_result = AuthResult(
            is_authenticated=True, user_id="user-123", token=auth_token, error=None
        )
        middleware.auth_provider.verify_token.return_value = auth_result

        # Capture context
        captured_context = None

        async def call_next_with_capture(request):
            nonlocal captured_context
            captured_context = ContextManager.get_context()
            return MagicMock(status_code=200)

        mock_call_next.side_effect = call_next_with_capture

        response = await middleware.dispatch(mock_request, mock_call_next)

        assert captured_context is not None
        assert captured_context.workspace_id == "custom-workspace"
        assert captured_context.user_id == "user-123"

    @pytest.mark.asyncio
    async def test_workspace_id_default(self, middleware, mock_request, mock_call_next):
        """Test that workspace ID defaults to 'default' when not provided."""
        mock_request.url.path = "/v1/agents"
        mock_request.headers = {"Authorization": "Bearer valid-token"}

        # Mock successful authentication
        auth_token = AuthToken(user_id="user-123", email="test@example.com")
        auth_result = AuthResult(
            is_authenticated=True, user_id="user-123", token=auth_token, error=None
        )
        middleware.auth_provider.verify_token.return_value = auth_result

        # Capture context
        captured_context = None

        async def call_next_with_capture(request):
            nonlocal captured_context
            captured_context = ContextManager.get_context()
            return MagicMock(status_code=200)

        mock_call_next.side_effect = call_next_with_capture

        response = await middleware.dispatch(mock_request, mock_call_next)

        assert captured_context is not None
        assert captured_context.workspace_id == "default"

    @pytest.mark.asyncio
    async def test_context_cleanup_after_request(
        self, middleware, mock_request, mock_call_next
    ):
        """Test that context is cleaned up after request."""
        mock_request.url.path = "/v1/agents"
        mock_request.headers = {"Authorization": "Bearer valid-token"}

        # Mock successful authentication
        auth_token = AuthToken(user_id="user-123", email="test@example.com")
        auth_result = AuthResult(
            is_authenticated=True, user_id="user-123", token=auth_token, error=None
        )
        middleware.auth_provider.verify_token.return_value = auth_result

        # Clear any existing context
        ContextManager.clear_context()

        await middleware.dispatch(mock_request, mock_call_next)

        # Context should be cleared after request
        assert ContextManager.get_context() is None

    @pytest.mark.asyncio
    async def test_unexpected_error_handling(self, middleware, mock_request, mock_call_next):
        """Test that unexpected errors are handled gracefully."""
        mock_request.url.path = "/v1/agents"
        mock_request.headers = {"Authorization": "Bearer valid-token"}

        # Mock unexpected error
        middleware.auth_provider.verify_token.side_effect = Exception("Unexpected error")

        response = await middleware.dispatch(mock_request, mock_call_next)

        mock_call_next.assert_not_called()
        assert isinstance(response, JSONResponse)
        assert response.status_code == 500

    @pytest.mark.asyncio
    async def test_context_cleanup_on_error(self, middleware, mock_request, mock_call_next):
        """Test that context is cleaned up even when error occurs."""
        mock_request.url.path = "/v1/agents"
        mock_request.headers = {"Authorization": "Bearer valid-token"}

        # Mock successful auth but error during request
        auth_token = AuthToken(user_id="user-123", email="test@example.com")
        auth_result = AuthResult(
            is_authenticated=True, user_id="user-123", token=auth_token, error=None
        )
        middleware.auth_provider.verify_token.return_value = auth_result

        # Clear any existing context
        ContextManager.clear_context()

        # Make call_next raise an error
        mock_call_next.side_effect = Exception("Request error")

        with pytest.raises(Exception, match="Request error"):
            await middleware.dispatch(mock_request, mock_call_next)

        # Context should still be cleared
        assert ContextManager.get_context() is None
