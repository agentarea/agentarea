"""Unit tests for authentication dependencies."""

from unittest.mock import AsyncMock, Mock, patch

import jwt
import pytest
from agentarea_common.auth import UserContext, UserPrincipal, get_user_context
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
        assert context.accessible_workspaces is None

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
        assert context.accessible_workspaces is None


def _kratos_accepts(user_id: str, email: str | None = None):
    from agentarea_common.auth.interfaces import AuthToken

    provider = Mock()
    provider.verify_token = AsyncMock(
        return_value=Mock(
            is_authenticated=True, token=AuthToken(user_id=user_id, email=email), error=None
        )
    )
    return provider


def _request(path_params: dict | None = None, headers: dict | None = None) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/v1/workspaces/x/agents",
            "query_string": b"",
            "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
            "path_params": path_params or {},
        }
    )


class TestAuthenticatePrincipal:
    """Authentication names the caller and nothing else."""

    @pytest.mark.asyncio
    @patch("agentarea_common.auth.dependencies.get_auth_provider")
    async def test_kratos_token_yields_a_principal_without_a_workspace(self, get_provider):
        from agentarea_common.auth.dependencies import authenticate_principal
        from fastapi.security import HTTPAuthorizationCredentials

        get_provider.return_value = _kratos_accepts("test-user", "test@example.com")
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="valid-token")

        principal = await authenticate_principal(_request(), credentials)

        assert isinstance(principal, UserPrincipal)
        assert principal.user_id == "test-user"
        assert principal.email == "test@example.com"
        assert not hasattr(principal, "workspace_id")

    @pytest.mark.asyncio
    @patch("agentarea_common.auth.dependencies.get_auth_provider")
    async def test_jwt_error_propagates_as_401(self, get_provider):
        from agentarea_common.auth.dependencies import authenticate_principal
        from fastapi.security import HTTPAuthorizationCredentials

        provider = Mock()
        provider.verify_token = AsyncMock(
            return_value=Mock(is_authenticated=False, token=None, error="Invalid token")
        )
        get_provider.return_value = provider
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="invalid-token")

        with (
            patch(
                "agentarea_common.auth.dependencies._try_hydra_token",
                new=AsyncMock(return_value=None),
            ),
            pytest.raises(HTTPException) as exc_info,
        ):
            await authenticate_principal(_request(), credentials)

        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_missing_credentials_is_401(self):
        from agentarea_common.auth.dependencies import authenticate_principal

        with pytest.raises(HTTPException) as exc_info:
            await authenticate_principal(_request(), None)

        assert exc_info.value.status_code == 401


class TestGetUserContext:
    """The workspace is the path slug; headers and defaults select nothing."""

    @pytest.fixture(autouse=True)
    def _authz(self):
        from agentarea_common.auth.authorization import AuthorizationService
        from agentarea_common.auth.workspace_authorization import (
            WorkspaceScopedAuthorizationService,
        )
        from agentarea_common.di.container import register_singleton

        register_singleton(AuthorizationService, WorkspaceScopedAuthorizationService())

    @pytest.mark.asyncio
    @patch("agentarea_common.auth.dependencies.ContextManager")
    async def test_member_workspace_is_selected_by_path_slug(self, context_manager):
        shared = Mock(id="ws-shared", slug="shared")
        with (
            patch(
                "agentarea_common.auth.dependencies._owned_and_named_workspaces",
                new=AsyncMock(return_value=([], shared)),
            ),
            patch(
                "agentarea_common.auth.dependencies._member_workspace_ids",
                new=AsyncMock(return_value=["ws-shared"]),
            ),
        ):
            context = await get_user_context(
                _request({"workspace": "shared"}, {"X-AgentArea-Workspace": "other"}),
                UserPrincipal(user_id="alice"),
            )

        assert context.workspace_id == "ws-shared"
        assert context.workspace_slug == "shared"
        context_manager.set_context.assert_called_once_with(context)

    @pytest.mark.asyncio
    async def test_hydra_principal_is_refused_a_foreign_workspace(self):
        foreign = Mock(id="ws-foreign", slug="foreign")
        with (
            patch(
                "agentarea_common.auth.dependencies._owned_and_named_workspaces",
                new=AsyncMock(return_value=([], foreign)),
            ),
            patch(
                "agentarea_common.auth.dependencies._member_workspace_ids",
                new=AsyncMock(return_value=[]),
            ),
            pytest.raises(HTTPException) as exc_info,
        ):
            await get_user_context(
                _request({"workspace": "foreign"}), UserPrincipal(user_id="alice")
            )

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_a_database_failure_is_not_a_missing_workspace(self):
        with (
            patch(
                "agentarea_common.auth.dependencies._owned_and_named_workspaces",
                new=AsyncMock(side_effect=RuntimeError("database is down")),
            ),
            patch(
                "agentarea_common.auth.dependencies._member_workspace_ids",
                new=AsyncMock(return_value=[]),
            ),
            pytest.raises(RuntimeError, match="database is down"),
        ):
            await get_user_context(
                _request({"workspace": "shared"}), UserPrincipal(user_id="alice")
            )


@pytest.mark.asyncio
async def test_accessible_workspaces_include_owned_and_joined_workspaces():
    from agentarea_common.auth.authorization import AuthorizationService
    from agentarea_common.auth.dependencies import _resolve_access
    from agentarea_common.di.container import register_singleton

    authz = Mock(spec=AuthorizationService)
    authz.get_accessible_workspaces = AsyncMock(return_value=[])
    register_singleton(AuthorizationService, authz)

    owned = Mock(id="owned-workspace", slug="owned", owner_user_id="alice")
    named = Mock(id="named-workspace", slug="named", owner_user_id="bob")
    repository = Mock()
    repository.list_owned_or_named = AsyncMock(return_value=[owned, named])
    session_context = AsyncMock()
    session_context.__aenter__.return_value = AsyncMock()
    database = Mock()
    database.async_session_factory.return_value = session_context

    principal = UserPrincipal(user_id="alice")
    with (
        patch(
            "agentarea_common.auth.dependencies._member_workspace_ids",
            new=AsyncMock(return_value=["joined-workspace"]),
        ),
        patch("agentarea_common.config.database.get_database", return_value=database),
        patch(
            "agentarea_common.workspaces.repository.WorkspaceRepository",
            return_value=repository,
        ),
    ):
        resolved = await _resolve_access(principal, slug="named")

    assert resolved is named
    assert principal.accessible_workspaces == ["joined-workspace", "owned-workspace"]
    assert principal.admin_workspaces == ["owned-workspace"]
    repository.list_owned_or_named.assert_awaited_once_with(
        "alice", slug="named", workspace_id=None
    )


@pytest.mark.asyncio
async def test_api_key_reach_is_narrowed_to_its_workspace():
    from agentarea_common.auth.authorization import AuthorizationService
    from agentarea_common.auth.dependencies import _resolve_access
    from agentarea_common.di.container import register_singleton

    authz = Mock(spec=AuthorizationService)
    authz.get_accessible_workspaces = AsyncMock(return_value=[])
    register_singleton(AuthorizationService, authz)
    owned = Mock(id="owned-workspace", owner_user_id="alice")

    principal = UserPrincipal(user_id="alice", bound_workspace_id="joined-workspace")
    with (
        patch(
            "agentarea_common.auth.dependencies._member_workspace_ids",
            new=AsyncMock(return_value=["joined-workspace"]),
        ),
        patch(
            "agentarea_common.auth.dependencies._owned_and_named_workspaces",
            new=AsyncMock(return_value=([owned], None)),
        ),
    ):
        await _resolve_access(principal)

    assert principal.accessible_workspaces == ["joined-workspace"]
    assert principal.admin_workspaces == []


@pytest.mark.asyncio
async def test_mcp_workspace_reference_accepts_slug_or_id():
    from agentarea_common.auth.dependencies import enter_workspace

    shared_id = "0d5c2f7e-8d6b-4b53-9a4e-1f7f3c2d9a10"
    shared = Mock(id=shared_id, slug="shared-slug")
    principal = UserPrincipal(user_id="alice", accessible_workspaces=[shared_id])

    async def load(*, workspace_id=None, slug=None):
        return shared if slug == "shared-slug" or workspace_id == shared_id else None

    with patch("agentarea_common.workspaces.lookup.load_workspace", new=load):
        by_slug = await enter_workspace(principal, "shared-slug")
        by_id = await enter_workspace(principal, shared_id)

    assert by_slug.workspace_id == by_id.workspace_id == shared_id
    assert by_slug.workspace_slug == "shared-slug"


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
    assert not hasattr(context, "workspace_id")


@pytest.mark.asyncio
async def test_hydra_token_without_a_user_is_refused():
    """A client_credentials token names the client as its subject; nobody logged in."""
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
                "sub": "90eaf1b8-5c71-48a5-a5f2-8da8c9a66771",
                "client_id": "90eaf1b8-5c71-48a5-a5f2-8da8c9a66771",
            },
        ),
    ):
        context = await _try_hydra_token("oauth-token", Mock(spec=Request))

    assert context is None


@pytest.mark.asyncio
async def test_hydra_token_issued_to_a_user_through_a_client_is_accepted():
    from agentarea_common.auth.dependencies import _try_hydra_token

    jwks = Mock()
    jwks.get_signing_key_from_jwt.return_value = Mock(key="public-key")
    settings = Mock()
    settings.mcp.HYDRA_AUDIENCE = "https://api.example.test"

    with (
        patch("agentarea_common.auth.dependencies._get_hydra_jwks", return_value=jwks),
        patch("agentarea_common.config.get_settings", return_value=settings),
        patch("jwt.decode", return_value={"sub": "alice", "client_id": "codex-client"}),
    ):
        context = await _try_hydra_token("oauth-token", Mock(spec=Request))

    assert context is not None
    assert context.user_id == "alice"
