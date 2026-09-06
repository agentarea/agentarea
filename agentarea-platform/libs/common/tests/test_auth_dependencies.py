"""Unit tests for authentication dependencies."""

from unittest.mock import AsyncMock, Mock, patch

import jwt
import pytest
from agentarea_common.auth import UserContext, get_user_context
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
        }
        token = jwt.encode(payload, "test-secret", algorithm="HS256")
        mock_request.headers = {"authorization": f"Bearer {token}"}

        context = await jwt_handler.extract_user_context(mock_request)

        assert isinstance(context, UserContext)
        assert context.user_id == "test-user-123"
        assert context.workspace_id == "test-workspace-456"
        assert context.accessible_workspaces == ["test-workspace-456"]

    @pytest.mark.asyncio
    async def test_extract_user_context_missing_token(self, jwt_handler, mock_request):
        """Test user context extraction when token is missing."""
        from agentarea_common.exceptions.workspace import InvalidJWTToken

        mock_request.headers = {}

        with pytest.raises(InvalidJWTToken) as exc_info:
            await jwt_handler.extract_user_context(mock_request)

        assert "Missing authorization token" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_extract_user_context_invalid_token(self, jwt_handler, mock_request):
        """Test user context extraction with invalid JWT token."""
        from agentarea_common.exceptions.workspace import InvalidJWTToken

        mock_request.headers = {"authorization": "Bearer invalid-token"}

        with pytest.raises(InvalidJWTToken) as exc_info:
            await jwt_handler.extract_user_context(mock_request)

        assert "Invalid" in str(exc_info.value) or "decode" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_extract_user_context_missing_sub_claim(self, jwt_handler, mock_request):
        """Test user context extraction when 'sub' claim is missing."""
        from agentarea_common.exceptions.workspace import MissingWorkspaceContext

        payload = {"workspace_id": "test-workspace-456"}
        token = jwt.encode(payload, "test-secret", algorithm="HS256")
        mock_request.headers = {"authorization": f"Bearer {token}"}

        with pytest.raises(MissingWorkspaceContext) as exc_info:
            await jwt_handler.extract_user_context(mock_request)

        assert "sub" in str(exc_info.value).lower() or "user_id" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_extract_user_context_missing_workspace_claim(self, jwt_handler, mock_request):
        """Test user context extraction when 'workspace_id' claim is missing."""
        from agentarea_common.exceptions.workspace import MissingWorkspaceContext

        payload = {"sub": "test-user-123"}
        token = jwt.encode(payload, "test-secret", algorithm="HS256")
        mock_request.headers = {"authorization": f"Bearer {token}"}

        with pytest.raises(MissingWorkspaceContext) as exc_info:
            await jwt_handler.extract_user_context(mock_request)

        assert "workspace" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_extract_user_context_minimal_claims(self, jwt_handler, mock_request):
        """Test user context extraction with minimal required claims."""
        payload = {"sub": "test-user-123", "workspace_id": "test-workspace-456"}
        token = jwt.encode(payload, "test-secret", algorithm="HS256")
        mock_request.headers = {"authorization": f"Bearer {token}"}

        context = await jwt_handler.extract_user_context(mock_request)

        assert context.user_id == "test-user-123"
        assert context.workspace_id == "test-workspace-456"
        assert context.accessible_workspaces == ["test-workspace-456"]


class TestGetUserContext:
    """Test cases for get_user_context dependency function."""

    @pytest.fixture
    def mock_request(self):
        """Create mock request object."""
        request = Mock(spec=Request)
        request.headers = {}
        return request

    @pytest.mark.asyncio
    @patch("agentarea_common.auth.dependencies.get_auth_provider")
    @patch("agentarea_common.auth.dependencies.ContextManager")
    async def test_get_user_context_success(
        self, mock_context_manager, mock_get_auth_provider, mock_request
    ):
        """Test successful user context extraction and context manager setting."""
        from agentarea_common.auth.authorization import AuthorizationService
        from agentarea_common.auth.interfaces import AuthToken
        from agentarea_common.di.container import register_singleton

        # Register a mock AuthorizationService that allows "test-workspace"
        mock_authz = Mock(spec=AuthorizationService)

        async def mock_get_accessible_workspaces(user_context):
            return [user_context.workspace_id, "test-workspace", "platform"]

        mock_authz.get_accessible_workspaces = mock_get_accessible_workspaces
        register_singleton(AuthorizationService, mock_authz)

        # Setup mocks
        mock_auth_provider = Mock()
        mock_get_auth_provider.return_value = mock_auth_provider

        # Create mock token and auth result
        mock_token = AuthToken(user_id="test-user", email="test@example.com")
        mock_auth_result = Mock()
        mock_auth_result.is_authenticated = True
        mock_auth_result.token = mock_token
        mock_auth_result.error = None

        # Make verify_token async
        async def mock_verify_token(token):
            return mock_auth_result

        mock_auth_provider.verify_token = mock_verify_token

        # Mock request headers — X-Workspace-ID override is only honoured if
        # the user is a member; our mock authz returns "test-workspace" so this
        # should succeed.
        mock_request.headers = {"X-Workspace-ID": "test-workspace"}

        # Call the dependency with valid credentials
        from fastapi.security import HTTPAuthorizationCredentials

        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="valid-token")

        result = await get_user_context(mock_request, credentials)

        # Verify results
        assert result.user_id == "test-user"
        assert result.workspace_id == "test-workspace"
        mock_context_manager.set_context.assert_called_once()

    @pytest.mark.asyncio
    @patch("agentarea_common.auth.dependencies.get_auth_provider")
    async def test_get_user_context_jwt_error_propagation(
        self, mock_get_auth_provider, mock_request
    ):
        """Test that JWT errors are properly propagated."""
        # Setup mocks
        mock_auth_provider = Mock()
        mock_get_auth_provider.return_value = mock_auth_provider

        # Mock failed authentication
        mock_auth_result = Mock()
        mock_auth_result.is_authenticated = False
        mock_auth_result.token = None
        mock_auth_result.error = "Invalid token"

        async def mock_verify_token(token):
            return mock_auth_result

        mock_auth_provider.verify_token = mock_verify_token

        # Call the dependency and verify exception is raised
        from fastapi.security import HTTPAuthorizationCredentials

        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="invalid-token")

        with pytest.raises(HTTPException) as exc_info:
            await get_user_context(mock_request, credentials)

        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    @patch("agentarea_common.auth.dependencies._resolve_accessible_workspaces")
    @patch("agentarea_common.auth.dependencies._try_hydra_token")
    @patch("agentarea_common.auth.dependencies.get_auth_provider")
    async def test_hydra_workspace_header_is_applied(
        self,
        mock_get_auth_provider,
        mock_try_hydra_token,
        mock_resolve_accessible,
        mock_request,
    ):
        rejected = Mock(is_authenticated=False, token=None, error="not a Kratos token")
        mock_provider = Mock()
        mock_provider.verify_token = AsyncMock(return_value=rejected)
        mock_get_auth_provider.return_value = mock_provider

        hydra_context = UserContext(user_id="alice", workspace_id="alice")
        mock_try_hydra_token.return_value = hydra_context

        async def grant_shared(context):
            context.accessible_workspaces = ["alice", "shared-workspace"]

        mock_resolve_accessible.side_effect = grant_shared
        mock_request.headers = {"X-AgentArea-Workspace": "shared-workspace"}

        from fastapi.security import HTTPAuthorizationCredentials

        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="hydra-token")
        result = await get_user_context(mock_request, credentials)

        assert result.workspace_id == "shared-workspace"


@pytest.mark.asyncio
async def test_accessible_workspaces_include_owned_workspaces():
    from agentarea_common.auth.authorization import AuthorizationService
    from agentarea_common.auth.dependencies import _resolve_accessible_workspaces
    from agentarea_common.di.container import register_singleton

    authz = Mock(spec=AuthorizationService)
    authz.get_accessible_workspaces = AsyncMock(return_value=["personal"])
    register_singleton(AuthorizationService, authz)

    owned = Mock(id="owned-workspace")
    repository = Mock()
    repository.list_owned_by_user = AsyncMock(return_value=[owned])
    session = AsyncMock()
    session_context = AsyncMock()
    session_context.__aenter__.return_value = session
    database = Mock()
    database.async_session_factory.return_value = session_context

    user_context = UserContext(user_id="alice", workspace_id="personal")
    with (
        patch(
            "agentarea_common.workspaces.memberships.get_workspace_membership_graph",
            return_value=None,
        ),
        patch("agentarea_common.config.database.get_database", return_value=database),
        patch(
            "agentarea_common.workspaces.repository.WorkspaceRepository",
            return_value=repository,
        ),
    ):
        await _resolve_accessible_workspaces(user_context)

    assert user_context.accessible_workspaces == ["personal", "owned-workspace"]
    repository.list_owned_by_user.assert_awaited_once_with("alice")


@pytest.mark.asyncio
async def test_canonical_workspace_reference_accepts_slug():
    from agentarea_common.auth.dependencies import _apply_workspace_selection

    request = Mock(spec=Request)
    request.headers = {"X-AgentArea-Workspace": "shared-slug"}
    user_context = UserContext(
        user_id="alice",
        workspace_id="personal",
        accessible_workspaces=["personal", "shared-id"],
    )

    with patch(
        "agentarea_common.auth.dependencies._resolve_workspace_id_from_slug",
        new=AsyncMock(return_value="shared-id"),
    ):
        await _apply_workspace_selection(user_context, request)

    assert user_context.workspace_id == "shared-id"


@pytest.mark.asyncio
async def test_hydra_token_workspace_claim_is_ignored():
    from agentarea_common.auth.dependencies import _try_hydra_token

    jwks = Mock()
    jwks.get_signing_key_from_jwt.return_value = Mock(key="public-key")
    settings = Mock()
    settings.mcp.HYDRA_AUDIENCE = "https://api.example.test"

    with (
        patch("agentarea_common.auth.dependencies._get_hydra_jwks", return_value=jwks),
        patch("agentarea_common.config.get_settings", return_value=settings),
        patch(
            "jwt.decode",
            return_value={
                "sub": "alice",
                "ext": {"workspace_id": "foreign-workspace"},
            },
        ),
    ):
        context = await _try_hydra_token("oauth-token", Mock(spec=Request))

    assert context is not None
    assert context.user_id == "alice"
    assert context.workspace_id == "alice"
