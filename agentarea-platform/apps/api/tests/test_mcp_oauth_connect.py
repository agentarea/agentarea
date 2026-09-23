import urllib.parse
from types import SimpleNamespace
from unittest.mock import AsyncMock, call
from uuid import uuid4

import pytest
from agentarea_api.api.v1 import mcp_oauth_connect
from agentarea_api.api.v1.mcp_oauth_connect import (
    MCPOAuthAuthorizeRequest,
    _instance_detail_url,
    _resolve_instance_remote_url,
)
from agentarea_common.auth.context import UserContext
from agentarea_common.testing.flows import MainFlow
from agentarea_mcp.application.oauth_client_service import (
    AuthServerMetadata,
    MCPOAuthDiscoveryError,
)
from fastapi import HTTPException


@pytest.mark.flow(MainFlow.MCP_OAUTH)
def test_resolve_instance_remote_url_uses_server_spec_remote_url():
    server_spec = SimpleNamespace(remote_url="https://server.example/mcp", json_spec={})

    assert _resolve_instance_remote_url(server_spec) == "https://server.example/mcp"


def test_resolve_instance_remote_url_uses_server_spec_json_fallback():
    server_spec = SimpleNamespace(
        remote_url=None,
        json_spec={"type": "url", "endpoint_url": "https://json-spec.example/mcp"},
    )

    assert _resolve_instance_remote_url(server_spec) == "https://json-spec.example/mcp"


def test_resolve_instance_remote_url_returns_none_without_remote_url():
    server_spec = SimpleNamespace(remote_url=None, json_spec={"type": "docker"})

    assert _resolve_instance_remote_url(server_spec) is None


@pytest.mark.flow(MainFlow.MCP_OAUTH)
def test_callback_returns_the_user_to_the_connection_page():
    """The page an MCP instance is shown on is /connections, not the retired
    /mcp-servers — a user finishing OAuth must land on their connection."""
    detail = _instance_detail_url("https://app.example", "d50241d7-eafe-4011-8479-b40f7a2aab3c")

    assert detail == "https://app.example/connections/d50241d7-eafe-4011-8479-b40f7a2aab3c"


# ---------------------------------------------------------------------------
# Shared fixtures for the endpoint-level tests
# ---------------------------------------------------------------------------

_GMAIL_URL = "https://gmailmcp.googleapis.com/mcp/v1"
_GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]


def _google_metadata(*, registration_endpoint: str | None = None) -> AuthServerMetadata:
    return AuthServerMetadata(
        issuer="https://accounts.google.com",
        authorization_endpoint="https://accounts.google.com/o/oauth2/v2/auth",
        token_endpoint="https://oauth2.googleapis.com/token",  # noqa: S106
        registration_endpoint=registration_endpoint,
        scopes_supported=list(_GMAIL_SCOPES),
        resource="https://gmailmcp.googleapis.com/mcp",
    )


def _patch_instance_lookup(monkeypatch, *, auth_config_id=None, remote_url: str | None = _GMAIL_URL):
    """Point the endpoint at one URL-type instance without touching a database."""
    instance = SimpleNamespace(
        id=uuid4(),
        server_spec_id=uuid4(),
        auth_config_id=auth_config_id,
        name="Gmail",
    )
    server_spec = SimpleNamespace(remote_url=remote_url, json_spec={"type": "url"})

    class _InstanceRepository:
        def __init__(self, *_args, **_kwargs):
            pass

        async def get_by_id(self, _requested_id):
            return instance

        update = AsyncMock(return_value=instance)

    class _ServerRepository:
        def __init__(self, *_args, **_kwargs):
            pass

        async def get_server_by_id(self, _requested_id):
            return server_spec

    monkeypatch.setattr(mcp_oauth_connect, "MCPServerInstanceRepository", _InstanceRepository)
    monkeypatch.setattr(mcp_oauth_connect, "MCPServerRepository", _ServerRepository)
    return instance


def _patch_discovery(monkeypatch, result):
    """Replace the network-backed discovery with a fixed outcome."""

    async def _discover(_self, _url):
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(
        mcp_oauth_connect.MCPOAuthClientService, "discover_auth_server", _discover, raising=True
    )


def _user_context() -> UserContext:
    return UserContext(user_id=str(uuid4()), workspace_id=str(uuid4()))


# ---------------------------------------------------------------------------
# Preflight — what the UI must ask for before it can offer Connect
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.flow(MainFlow.MCP_OAUTH)
async def test_preflight_requires_an_oauth_app_when_the_server_has_no_dcr(monkeypatch):
    """Google publishes no registration_endpoint, so AgentArea cannot register
    itself. The UI has to collect a client ID/secret rather than render a
    Connect button whose only possible outcome is a failure."""
    _patch_instance_lookup(monkeypatch)
    _patch_discovery(monkeypatch, _google_metadata())

    result = await mcp_oauth_connect.oauth_preflight(
        _user_context(), AsyncMock(), instance_id=uuid4()
    )

    assert result.status == "oauth_app_required"
    assert result.connected is False
    assert result.issuer == "https://accounts.google.com"
    assert result.scopes == _GMAIL_SCOPES
    assert "accounts.google.com" in result.detail


@pytest.mark.asyncio
async def test_preflight_is_ready_when_the_server_supports_dcr(monkeypatch):
    _patch_instance_lookup(monkeypatch)
    _patch_discovery(
        monkeypatch, _google_metadata(registration_endpoint="https://as.example.com/register")
    )

    result = await mcp_oauth_connect.oauth_preflight(
        _user_context(), AsyncMock(), instance_id=uuid4()
    )

    assert result.status == "ready"


@pytest.mark.asyncio
async def test_preflight_reports_connected_instances(monkeypatch):
    _patch_instance_lookup(monkeypatch, auth_config_id=uuid4())
    _patch_discovery(monkeypatch, _google_metadata())

    result = await mcp_oauth_connect.oauth_preflight(
        _user_context(), AsyncMock(), instance_id=uuid4()
    )

    assert result.connected is True


@pytest.mark.asyncio
@pytest.mark.flow(MainFlow.MCP_OAUTH)
async def test_preflight_answers_unsupported_instead_of_failing(monkeypatch):
    """Preflight answers a question about capability. A server without OAuth
    discovery is a valid answer ("no button here"), not a 502 the UI has to
    decode from an error toast."""
    _patch_instance_lookup(monkeypatch)
    _patch_discovery(monkeypatch, MCPOAuthDiscoveryError("no protected-resource metadata"))

    result = await mcp_oauth_connect.oauth_preflight(
        _user_context(), AsyncMock(), instance_id=uuid4()
    )

    assert result.status == "unsupported"
    assert "no protected-resource metadata" in result.detail


@pytest.mark.asyncio
async def test_preflight_reports_unsupported_for_an_instance_without_a_remote_url(monkeypatch):
    _patch_instance_lookup(monkeypatch, remote_url=None)

    result = await mcp_oauth_connect.oauth_preflight(
        _user_context(), AsyncMock(), instance_id=uuid4()
    )

    assert result.status == "unsupported"
    assert "remote URL" in result.detail


# ---------------------------------------------------------------------------
# Authorize — request validation
# ---------------------------------------------------------------------------


@pytest.mark.flow(MainFlow.MCP_OAUTH)
def test_authorize_request_rejects_credentials_in_auto_mode():
    with pytest.raises(ValueError, match="do not accept custom OAuth credentials"):
        MCPOAuthAuthorizeRequest(instance_id=uuid4(), client_id="cid")


def test_authorize_request_requires_exactly_one_source_per_credential():
    with pytest.raises(ValueError, match="client ID must be entered or selected"):
        MCPOAuthAuthorizeRequest(
            instance_id=uuid4(),
            credential_mode="custom",
            client_secret="shh",  # noqa: S106  # pragma: allowlist secret
        )

    with pytest.raises(ValueError, match="client secret must be entered or selected"):
        MCPOAuthAuthorizeRequest(
            instance_id=uuid4(),
            credential_mode="custom",
            client_id="cid",
            client_secret="shh",  # noqa: S106  # pragma: allowlist secret
            client_secret_secret_id=uuid4(),
        )


# ---------------------------------------------------------------------------
# Authorize — behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.flow(MainFlow.MCP_OAUTH)
async def test_authorize_without_dcr_asks_for_an_oauth_app_not_for_server_env_vars(monkeypatch):
    """The old fallback told every tenant to set MCP_OAUTH_CLIENT_ID on the
    server — one global app shared across unrelated workspaces, and advice no
    tenant can act on. Refuse with the machine-readable reason the UI already
    renders instead."""
    _patch_instance_lookup(monkeypatch)
    _patch_discovery(monkeypatch, _google_metadata())

    with pytest.raises(HTTPException) as excinfo:
        await mcp_oauth_connect.oauth_authorize(
            MCPOAuthAuthorizeRequest(instance_id=uuid4()),
            _user_context(),
            AsyncMock(),
            AsyncMock(),
        )

    assert excinfo.value.status_code == 422
    assert excinfo.value.detail["code"] == "oauth_app_required"
    assert "MCP_OAUTH_CLIENT_ID" not in str(excinfo.value.detail)


@pytest.mark.asyncio
@pytest.mark.flow(MainFlow.MCP_OAUTH)
@pytest.mark.parametrize("credential_source", ["inline", "workspace_secrets"])
async def test_authorize_with_a_custom_oauth_app_keeps_the_secret_out_of_state(
    monkeypatch, credential_source
):
    """A workspace's own OAuth app is persisted on an auth config before the
    redirect, so the OAuth state in Redis carries a reference and never a
    client secret."""
    instance = _patch_instance_lookup(monkeypatch)
    _patch_discovery(monkeypatch, _google_metadata())
    auth_config_id = uuid4()
    auth_create = AsyncMock(return_value=SimpleNamespace(id=auth_config_id))

    class _AuthService:
        def __init__(self, *_args, **_kwargs):
            pass

        create = auth_create

    client_id_secret = SimpleNamespace(
        id=uuid4(),
        secret_name="gmail_client_id",  # noqa: S106  # pragma: allowlist secret
        owner_type=None,
    )
    client_secret_secret = SimpleNamespace(
        id=uuid4(),
        secret_name="gmail_client_secret",  # noqa: S106  # pragma: allowlist secret
        owner_type=None,
    )
    workspace_manager = SimpleNamespace(
        get_secret=AsyncMock(
            side_effect=lambda name: {
                "gmail_client_id": "workspace-client-id",
                "gmail_client_secret": "workspace-client-secret",  # pragma: allowlist secret
            }.get(name)
        )
    )
    secret_catalog = SimpleNamespace(
        get=AsyncMock(side_effect=[client_id_secret, client_secret_secret]),
        add_reference=AsyncMock(),
    )
    stored_state = AsyncMock()
    monkeypatch.setattr(mcp_oauth_connect, "MCPAuthService", _AuthService)
    monkeypatch.setattr(
        mcp_oauth_connect, "get_real_secret_manager", lambda **_kwargs: workspace_manager
    )
    monkeypatch.setattr(mcp_oauth_connect, "_store_state", stored_state)
    monkeypatch.setattr(
        mcp_oauth_connect,
        "_callback_uri",
        lambda: "https://api.agentarea.ru/v1/mcp-oauth/callback",
    )

    if credential_source == "inline":
        body = MCPOAuthAuthorizeRequest(
            instance_id=instance.id,
            credential_mode="custom",
            client_id="inline-client-id",
            client_secret="inline-client-secret",  # noqa: S106  # pragma: allowlist secret
        )
    else:
        body = MCPOAuthAuthorizeRequest(
            instance_id=instance.id,
            credential_mode="custom",
            client_id_secret_id=client_id_secret.id,
            client_secret_secret_id=client_secret_secret.id,
        )

    response = await mcp_oauth_connect.oauth_authorize(
        body, _user_context(), AsyncMock(), secret_catalog
    )

    query = urllib.parse.parse_qs(urllib.parse.urlparse(response["authorize_url"]).query)
    expected_client_id = {
        "inline": "inline-client-id",
        "workspace_secrets": "workspace-client-id",  # pragma: allowlist secret
    }[credential_source]
    assert query["client_id"] == [expected_client_id]
    assert query["redirect_uri"] == ["https://api.agentarea.ru/v1/mcp-oauth/callback"]
    # The Gmail scopes come from the resource metadata — authorizing without
    # them consents to nothing the MCP server accepts.
    assert _GMAIL_SCOPES[0] in query["scope"][0]
    assert query["code_challenge_method"] == ["S256"]

    auth_kwargs = auth_create.await_args.kwargs
    if credential_source == "inline":
        assert auth_kwargs["config"]["client_id"] == "inline-client-id"
        assert auth_kwargs["credentials"] == {  # pragma: allowlist secret
            "client_secret": "inline-client-secret"  # pragma: allowlist secret
        }
        secret_catalog.add_reference.assert_not_awaited()
    else:
        assert auth_kwargs["credentials"] == {}
        assert "client_id" not in auth_kwargs["config"]
        assert auth_kwargs["config"]["client_id_secret_name"] == "gmail_client_id"  # noqa: S105
        assert (
            auth_kwargs["config"]["client_secret_secret_name"]  # noqa: S105
            == "gmail_client_secret"  # pragma: allowlist secret
        )
        assert secret_catalog.add_reference.await_args_list == [
            call(client_id_secret.id, "mcp_auth_config", str(auth_config_id), "client_id"),
            call(client_secret_secret.id, "mcp_auth_config", str(auth_config_id), "client_secret"),
        ]

    state_payload = stored_state.await_args.args[1]
    assert "client_secret" not in state_payload
    assert state_payload["auth_config_id"] == str(auth_config_id)
    assert state_payload["instance_id"] == str(instance.id)


@pytest.mark.asyncio
async def test_authorize_persists_dcr_credentials_before_redirecting(monkeypatch):
    """Dynamically registered credentials are needed again at token exchange and
    refresh, so they belong on the auth config, not in expiring Redis state."""
    instance = _patch_instance_lookup(monkeypatch)
    _patch_discovery(
        monkeypatch, _google_metadata(registration_endpoint="https://as.example.com/register")
    )
    auth_create = AsyncMock(return_value=SimpleNamespace(id=uuid4()))

    class _AuthService:
        def __init__(self, *_args, **_kwargs):
            pass

        create = auth_create

    async def _register_client(_self, _metadata, _redirect_uri):
        return SimpleNamespace(client_id="dcr-client-id", client_secret="dcr-secret")

    monkeypatch.setattr(mcp_oauth_connect, "MCPAuthService", _AuthService)
    monkeypatch.setattr(
        mcp_oauth_connect, "get_real_secret_manager", lambda **_kwargs: SimpleNamespace()
    )
    monkeypatch.setattr(mcp_oauth_connect, "_store_state", AsyncMock())
    monkeypatch.setattr(
        mcp_oauth_connect.MCPOAuthClientService, "register_client", _register_client, raising=True
    )

    response = await mcp_oauth_connect.oauth_authorize(
        MCPOAuthAuthorizeRequest(instance_id=instance.id),
        _user_context(),
        AsyncMock(),
        AsyncMock(),
    )

    query = urllib.parse.parse_qs(urllib.parse.urlparse(response["authorize_url"]).query)
    assert query["client_id"] == ["dcr-client-id"]
    auth_kwargs = auth_create.await_args.kwargs
    assert auth_kwargs["config"]["client_id"] == "dcr-client-id"
    assert auth_kwargs["credentials"]["client_secret"] == "dcr-secret"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "description",
    [
        "access_denied",
        "https://evil.example/phish",
        "//evil.example",
        "a&next=https://evil.example",
    ],
)
async def test_callback_error_returns_to_the_frontend_with_the_reason_as_data(
    monkeypatch, description
):
    monkeypatch.setattr(
        mcp_oauth_connect,
        "get_settings",
        lambda: SimpleNamespace(app=SimpleNamespace(FRONTEND_BASE_URL="https://app.agentarea.ai/")),
    )

    response = await mcp_oauth_connect.oauth_callback(
        db_session=None,
        code=None,
        state=None,
        error="access_denied",
        error_description=description,
    )

    location = urllib.parse.urlparse(response.headers["location"])
    assert (location.scheme, location.netloc, location.path) == (
        "https",
        "app.agentarea.ai",
        "/connections",
    )
    assert urllib.parse.parse_qs(location.query) == {"oauth": ["error"], "reason": [description]}
