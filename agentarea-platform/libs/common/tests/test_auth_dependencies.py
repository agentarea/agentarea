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


_API_AUDIENCE = "https://api.example.test"


def _kratos_with_its_own_key():
    """The real Kratos provider, holding only Kratos's key (not Hydra's)."""
    import json

    from agentarea_common.auth.providers.kratos import KratosAuthProvider
    from cryptography.hazmat.primitives.asymmetric import ec

    key = ec.generate_private_key(ec.SECP256R1())
    jwk = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(key.public_key()))
    jwks = {"keys": [{**jwk, "kid": "kratos-key", "use": "sig", "alg": "ES256"}]}
    provider = KratosAuthProvider(
        {"jwks_b64": json.dumps(jwks), "issuer": "http://kratos.test", "audience": "agentarea-api"}
    )
    return provider, key


def _hydra_jwks_client(fetch_data):
    """PyJWKClient for Hydra's JWKS, with the HTTP fetch replaced by *fetch_data*."""
    client = jwt.PyJWKClient("http://hydra.test/.well-known/jwks.json", cache_keys=True)
    client.fetch_data = fetch_data
    return client


def _raise(error: Exception):
    def fetch():
        raise error

    return fetch


class TestHydraTokenRefusal:
    """A token Hydra signed is judged by Hydra's rules, and says why it was refused."""

    @pytest.fixture
    def hydra(self, monkeypatch):
        import json
        import time

        from agentarea_common.auth import dependencies
        from cryptography.hazmat.primitives.asymmetric import rsa

        monkeypatch.setattr(dependencies, "_hydra_jwks_unavailable_logged_at", None)
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
        hydra_jwks = {"keys": [{**public_jwk, "kid": "hydra-key", "use": "sig", "alg": "RS256"}]}
        kratos, kratos_key = _kratos_with_its_own_key()
        settings = Mock(HYDRA_AUDIENCE=_API_AUDIENCE)
        jwks_client = Mock()

        def sign(*, expires_in: int = 3600, kid: str = "hydra-key", signer=key, **claims) -> str:
            now = int(time.time())
            payload = {
                "sub": "alice",
                "client_id": "agentarea-cli",
                "aud": [_API_AUDIENCE],
                "iss": "http://hydra.test/",
                "iat": now - 60,
                "exp": now + expires_in,
                **claims,
            }
            return jwt.encode(payload, signer, algorithm="RS256", headers={"kid": kid})

        def sign_kratos(*, expires_in: int) -> str:
            now = int(time.time())
            payload = {
                "sub": "bob",
                "aud": "agentarea-api",
                "iss": "http://kratos.test",
                "iat": now - 120,
                "exp": now + expires_in,
            }
            return jwt.encode(payload, kratos_key, algorithm="ES256", headers={"kid": "kratos-key"})

        def serve_jwks(fetch_data) -> None:
            jwks_client.current = _hydra_jwks_client(fetch_data)

        serve_jwks(lambda: hydra_jwks)
        with (
            patch(
                "agentarea_common.auth.dependencies._get_hydra_jwks",
                side_effect=lambda: jwks_client.current,
            ),
            patch("agentarea_common.config.get_auth_settings", return_value=settings),
            patch(
                "agentarea_common.auth.dependencies.get_auth_provider",
                return_value=kratos,
            ),
        ):
            yield Mock(
                sign=sign, sign_kratos=sign_kratos, serve_jwks=serve_jwks, settings=settings
            )

    @staticmethod
    async def _authenticate(token: str) -> UserPrincipal:
        from agentarea_common.auth.dependencies import authenticate_principal
        from fastapi.security import HTTPAuthorizationCredentials

        return await authenticate_principal(
            _request(), HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        )

    @pytest.mark.asyncio
    async def test_a_valid_hydra_token_is_accepted(self, hydra):
        principal = await self._authenticate(hydra.sign())

        assert principal.user_id == "alice"

    @pytest.mark.asyncio
    async def test_an_expired_hydra_token_is_reported_as_expired(self, hydra):
        with pytest.raises(HTTPException) as exc_info:
            await self._authenticate(hydra.sign(expires_in=-60))

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Token has expired"
        assert (exc_info.value.headers or {})["WWW-Authenticate"].startswith("Bearer ")

    @pytest.mark.asyncio
    async def test_a_hydra_token_for_another_audience_says_so(self, hydra, caplog):
        with pytest.raises(HTTPException) as exc_info:
            await self._authenticate(hydra.sign(aud=["https://other.example.test"]))

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Token was not issued for this API"
        assert any(
            r.levelname == "WARNING" and "Hydra" in r.getMessage() for r in caplog.records
        )

    @pytest.mark.asyncio
    async def test_a_hydra_token_without_a_user_says_so(self, hydra):
        with pytest.raises(HTTPException) as exc_info:
            await self._authenticate(hydra.sign(sub="agentarea-cli"))

        assert exc_info.value.status_code == 401
        assert "JWKS" not in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_a_hydra_token_is_refused_when_no_audience_is_configured(self, hydra):
        hydra.settings.HYDRA_AUDIENCE = None

        with pytest.raises(HTTPException) as exc_info:
            await self._authenticate(hydra.sign())

        assert exc_info.value.status_code == 401
        assert "JWKS" not in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_a_token_neither_kratos_nor_hydra_signed_keeps_the_kratos_reason(self, hydra):
        with pytest.raises(HTTPException) as exc_info:
            await self._authenticate(hydra.sign(kid="somebody-else"))

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Key not found in JWKS"

    @pytest.mark.asyncio
    async def test_a_hydra_token_with_a_forged_signature_says_so(self, hydra):
        from cryptography.hazmat.primitives.asymmetric import rsa

        forger = rsa.generate_private_key(public_exponent=65537, key_size=2048)

        with pytest.raises(HTTPException) as exc_info:
            await self._authenticate(hydra.sign(signer=forger))

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Token signature is invalid"

    @pytest.mark.asyncio
    async def test_a_hydra_token_workspace_claim_is_ignored(self, hydra):
        principal = await self._authenticate(hydra.sign(ext={"workspace_id": "foreign"}))

        assert principal.user_id == "alice"
        assert not hasattr(principal, "workspace_id")

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "fetch_data",
        [
            pytest.param(_raise(jwt.PyJWKClientConnectionError("refused")), id="unreachable"),
            pytest.param(lambda: "<html>Bad gateway</html>", id="not-a-json-object"),
            pytest.param(_raise(ValueError("Expecting value: line 1 column 1")), id="not-json"),
            pytest.param(lambda: {"keys": []}, id="no-keys"),
            pytest.param(lambda: {"keys": "nope"}, id="invalid-key-set"),
        ],
    )
    async def test_a_broken_hydra_jwks_leaves_an_expired_kratos_session_a_401(
        self, hydra, fetch_data
    ):
        hydra.serve_jwks(fetch_data)

        with pytest.raises(HTTPException) as exc_info:
            await self._authenticate(hydra.sign_kratos(expires_in=-60))

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Token has expired"

    @pytest.mark.asyncio
    async def test_an_unavailable_hydra_jwks_is_logged_once_not_per_request(
        self, hydra, caplog
    ):
        hydra.serve_jwks(_raise(jwt.PyJWKClientConnectionError("refused")))

        for _ in range(3):
            with pytest.raises(HTTPException):
                await self._authenticate(hydra.sign_kratos(expires_in=-60))

        warnings = [r for r in caplog.records if "Hydra's JWKS" in r.getMessage()]
        assert len(warnings) == 1
        assert warnings[0].levelname == "WARNING"
        assert warnings[0].exc_info is not None
