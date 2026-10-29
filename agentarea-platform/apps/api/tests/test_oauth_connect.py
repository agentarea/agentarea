"""One OAuth connect flow: MCP instances and catalog APIs, one callback."""

import json
import logging
import urllib.parse
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, call
from uuid import uuid4

import httpx
import pytest
from agentarea_api.api.v1 import oauth_connect as routes
from agentarea_api.api.v1.oauth_connect import OAuthAuthorizeRequest, OAuthFinishRequest
from agentarea_api.oauth_connect import pages, service, targets
from agentarea_api.oauth_connect import state as oauth_state
from agentarea_api.oauth_connect.state import OAuthState, ReturnedFlow
from agentarea_common.auth.authorization import AuthorizationService
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.workspace_authorization import WorkspaceScopedAuthorizationService
from agentarea_common.config.mcp import MCPSettings
from agentarea_common.di.container import register_singleton
from agentarea_common.exceptions import AppError
from agentarea_common.testing.flows import MainFlow
from agentarea_mcp.application import platform_oauth_app
from agentarea_mcp.application.auth_service import OAuthCodeExchangeError
from agentarea_mcp.application.oauth_client_service import (
    AuthServerMetadata,
    MCPOAuthClientService,
    MCPOAuthDiscoveryError,
)
from agentarea_secrets.catalog_service import SecretCatalogService
from fastapi import HTTPException

_API = "https://api.example.com"
_APP = "https://app.agentarea.ai"
_CALLBACK = f"{_API}/v1/oauth/callback"


@pytest.fixture(autouse=True)
def settings(monkeypatch):
    """One deployment: its frontend and its API, so its one callback URI."""
    monkeypatch.setattr(
        pages,
        "get_settings",
        lambda: SimpleNamespace(app=SimpleNamespace(APP_URL=f"{_APP}/", API_URL=f"{_API}/")),
    )


@pytest.fixture(autouse=True)
def platform_apps(monkeypatch):
    """AGENTAREA_MCP_OAUTH_APPS: none unless a test configures one."""
    configured: list[dict] = []
    monkeypatch.setattr(
        platform_oauth_app,
        "get_settings",
        lambda: SimpleNamespace(mcp=MCPSettings(OAUTH_APPS=configured)),
    )
    return configured


@pytest.fixture(autouse=True)
def allow_editing_the_instance(monkeypatch):
    """Authorize checks ``edit`` on an instance; the tests below are about the flow."""
    monkeypatch.setattr(targets, "require_permission", AsyncMock())


def _user_context() -> UserContext:
    return UserContext(user_id=str(uuid4()), workspace_id=str(uuid4()))


def _query(url: str) -> dict[str, list[str]]:
    return urllib.parse.parse_qs(urllib.parse.urlparse(url).query)


def test_the_callback_uri_is_one_neutral_path_on_the_api():
    assert pages.callback_uri() == _CALLBACK


# ---------------------------------------------------------------------------
# Remote MCP instances
# ---------------------------------------------------------------------------

_GMAIL_URL = "https://gmailmcp.googleapis.com/mcp/v1"
_GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]


def _server(*, remote_url=None, json_spec=None):
    return SimpleNamespace(
        remote_url=remote_url, cmd=None, docker_image_url=None, json_spec=json_spec or {}
    )


def _google_metadata(*, registration_endpoint: str | None = None) -> AuthServerMetadata:
    return AuthServerMetadata(
        issuer="https://accounts.google.com",
        authorization_endpoint="https://accounts.google.com/o/oauth2/v2/auth",
        token_endpoint="https://oauth2.googleapis.com/token",  # noqa: S106
        registration_endpoint=registration_endpoint,
        scopes_supported=list(_GMAIL_SCOPES),
        resource="https://gmailmcp.googleapis.com/mcp",
    )


def _patch_instance_lookup(
    monkeypatch,
    *,
    auth_config_id=None,
    remote_url: str | None = _GMAIL_URL,
    spec_metadata: dict | None = None,
):
    """Point the flow at one URL-type instance without touching a database."""
    instance = SimpleNamespace(
        id=uuid4(),
        server_spec_id=uuid4(),
        auth_config_id=auth_config_id,
        name="Gmail",
        transport="url",
        json_spec={},
    )
    json_spec: dict = {"type": "url"}
    if spec_metadata is not None:
        json_spec["metadata"] = spec_metadata
    server_spec = _server(remote_url=remote_url, json_spec=json_spec)

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

    monkeypatch.setattr(targets, "MCPServerInstanceRepository", _InstanceRepository)
    monkeypatch.setattr(targets, "MCPServerRepository", _ServerRepository)
    return instance


def _patch_discovery(monkeypatch, result):
    async def _discover(_self, _url):
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(MCPOAuthClientService, "discover_auth_server", _discover)


def _patch_authorize(monkeypatch, *, secret_manager=None):
    """Persisting the auth config and the state; returns both mocks."""
    auth_create = AsyncMock(return_value=SimpleNamespace(id=uuid4()))

    class _AuthService:
        def __init__(self, *_args, **_kwargs):
            pass

        create = auth_create

    stored_state = AsyncMock()
    monkeypatch.setattr(service, "MCPAuthService", _AuthService)
    monkeypatch.setattr(
        service,
        "get_real_secret_manager",
        lambda **_kwargs: secret_manager or SimpleNamespace(),
    )
    monkeypatch.setattr(oauth_state, "store", stored_state)
    return auth_create, stored_state


async def _preflight(**target):
    return await routes.oauth_preflight(_user_context(), AsyncMock(), **target)


async def _authorize(body: OAuthAuthorizeRequest, secret_catalog=None, user_context=None):
    return await routes.oauth_authorize(
        body, user_context or _user_context(), AsyncMock(), secret_catalog or AsyncMock()
    )


def test_an_instance_without_a_remote_url_has_none():
    instance = SimpleNamespace(transport="docker", json_spec={})

    assert targets.instance_remote_url(instance, _server(remote_url="https://x.example")) is None


def test_an_instance_uses_its_specs_json_endpoint():
    instance = SimpleNamespace(transport="url", json_spec={})
    spec = _server(json_spec={"type": "url", "endpoint_url": "https://json-spec.example/mcp"})

    assert targets.instance_remote_url(instance, spec) == "https://json-spec.example/mcp"


@pytest.mark.asyncio
@pytest.mark.flow(MainFlow.MCP_OAUTH)
async def test_preflight_requires_an_oauth_app_when_the_server_has_no_dcr(monkeypatch):
    """Google publishes no registration_endpoint, so AgentArea cannot register
    itself. The UI has to collect a client ID/secret rather than render a
    Connect button whose only possible outcome is a failure."""
    _patch_instance_lookup(monkeypatch)
    _patch_discovery(monkeypatch, _google_metadata())

    result = await _preflight(instance_id=uuid4())

    assert result.status == "oauth_app_required"
    assert result.credential_source is None
    assert result.connected is False
    assert result.issuer == "https://accounts.google.com"
    assert result.scopes == _GMAIL_SCOPES
    assert "accounts.google.com" in result.detail
    assert result.redirect_uri == _CALLBACK


@pytest.mark.asyncio
async def test_preflight_is_ready_with_dynamic_registration(monkeypatch):
    _patch_instance_lookup(monkeypatch)
    _patch_discovery(
        monkeypatch, _google_metadata(registration_endpoint="https://as.example.com/register")
    )

    result = await _preflight(instance_id=uuid4())

    assert result.status == "ready"
    assert result.credential_source == "dynamic"


@pytest.mark.asyncio
async def test_preflight_reports_connected_instances(monkeypatch):
    _patch_instance_lookup(monkeypatch, auth_config_id=uuid4())
    _patch_discovery(monkeypatch, _google_metadata())

    assert (await _preflight(instance_id=uuid4())).connected is True


@pytest.mark.asyncio
@pytest.mark.flow(MainFlow.MCP_OAUTH)
async def test_preflight_answers_unsupported_instead_of_failing(monkeypatch):
    """A server without OAuth discovery is a valid answer ("no button here"),
    not a 502 the UI has to decode from an error toast."""
    _patch_instance_lookup(monkeypatch)
    _patch_discovery(monkeypatch, MCPOAuthDiscoveryError("no protected-resource metadata"))

    result = await _preflight(instance_id=uuid4())

    assert result.status == "unsupported"
    assert "no protected-resource metadata" in result.detail


def _unreachable_mcp_host(monkeypatch):
    """Every outbound request the discovery makes fails to connect."""

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused", request=request)

    monkeypatch.setattr(
        "agentarea_mcp.application.oauth_client_service.safe_async_client",
        lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(refuse), **kwargs),
    )


@pytest.mark.asyncio
async def test_authorize_answers_502_when_the_mcp_host_is_unreachable(monkeypatch):
    instance = _patch_instance_lookup(monkeypatch)
    _unreachable_mcp_host(monkeypatch)

    with pytest.raises(HTTPException) as excinfo:
        await _authorize(OAuthAuthorizeRequest(instance_id=instance.id))

    assert excinfo.value.status_code == 502
    assert "Could not reach" in excinfo.value.detail


@pytest.mark.asyncio
async def test_preflight_answers_unsupported_when_the_mcp_host_is_unreachable(monkeypatch):
    _patch_instance_lookup(monkeypatch)
    _unreachable_mcp_host(monkeypatch)

    result = await _preflight(instance_id=uuid4())

    assert result.status == "unsupported"
    assert "Could not reach" in result.detail


@pytest.mark.asyncio
async def test_preflight_reports_unsupported_for_an_instance_without_a_remote_url(monkeypatch):
    _patch_instance_lookup(monkeypatch, remote_url=None)

    result = await _preflight(instance_id=uuid4())

    assert result.status == "unsupported"
    assert "remote URL" in result.detail


@pytest.mark.asyncio
@pytest.mark.flow(MainFlow.MCP_OAUTH)
async def test_preflight_answers_for_a_catalog_spec_before_any_instance_exists(monkeypatch):
    """The create page has to know whether to ask for an OAuth app before it
    creates anything."""
    _patch_instance_lookup(monkeypatch)
    _patch_discovery(monkeypatch, _google_metadata())

    result = await _preflight(server_id=uuid4())

    assert result.status == "oauth_app_required"
    assert result.connected is False


@pytest.mark.asyncio
async def test_preflight_for_an_unknown_spec_is_not_found(monkeypatch):
    class _NoServer:
        def __init__(self, *_args, **_kwargs):
            pass

        async def get_server_by_id(self, _requested_id):
            return None

    monkeypatch.setattr(targets, "MCPServerRepository", _NoServer)

    with pytest.raises(HTTPException) as excinfo:
        await _preflight(server_id=uuid4())

    assert excinfo.value.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "target",
    [
        {},
        {"instance_id": uuid4(), "server_id": uuid4()},
        {"instance_id": uuid4(), "catalog_item_id": uuid4()},
    ],
)
async def test_preflight_takes_exactly_one_target(target):
    with pytest.raises(HTTPException) as excinfo:
        await _preflight(**target)

    assert excinfo.value.status_code == 422


@pytest.mark.flow(MainFlow.MCP_OAUTH)
def test_authorize_request_rejects_credentials_in_auto_mode():
    with pytest.raises(ValueError, match="do not accept custom OAuth credentials"):
        OAuthAuthorizeRequest(instance_id=uuid4(), client_id="cid")


@pytest.mark.parametrize("target", [{}, {"instance_id": uuid4(), "catalog_item_id": uuid4()}])
def test_authorize_request_names_exactly_one_target(target):
    with pytest.raises(ValueError, match="exactly one of instance_id or catalog_item_id"):
        OAuthAuthorizeRequest(**target)


def test_authorize_request_requires_exactly_one_source_per_credential():
    with pytest.raises(ValueError, match="client ID must be entered or selected"):
        OAuthAuthorizeRequest(
            instance_id=uuid4(),
            credential_mode="custom",
            client_secret="shh",  # noqa: S106  # pragma: allowlist secret
        )

    with pytest.raises(ValueError, match="client secret must be entered or selected"):
        OAuthAuthorizeRequest(
            catalog_item_id=uuid4(),
            credential_mode="custom",
            client_id="cid",
            client_secret="shh",  # noqa: S106  # pragma: allowlist secret
            client_secret_secret_id=uuid4(),
        )


@pytest.mark.asyncio
@pytest.mark.flow(MainFlow.MCP_OAUTH)
async def test_authorize_refuses_a_member_who_cannot_edit_the_instance(monkeypatch):
    """Completing the flow attaches the caller's provider account to the
    instance, so starting it is an edit."""
    instance = _patch_instance_lookup(monkeypatch)
    discover = AsyncMock()
    monkeypatch.setattr(MCPOAuthClientService, "discover_auth_server", discover)
    deny = AsyncMock(side_effect=HTTPException(status_code=403, detail="Forbidden"))
    monkeypatch.setattr(targets, "require_permission", deny)
    user_context = _user_context()

    with pytest.raises(HTTPException) as excinfo:
        await _authorize(OAuthAuthorizeRequest(instance_id=instance.id), user_context=user_context)

    assert excinfo.value.status_code == 403
    deny.assert_awaited_once_with("edit", "mcp_instance", str(instance.id), user_context)
    discover.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.flow(MainFlow.MCP_OAUTH)
async def test_authorize_without_dcr_or_platform_app_asks_for_an_oauth_app(monkeypatch):
    _patch_instance_lookup(monkeypatch)
    _patch_discovery(monkeypatch, _google_metadata())
    auth_create, _ = _patch_authorize(monkeypatch)

    with pytest.raises(AppError) as excinfo:
        await _authorize(OAuthAuthorizeRequest(instance_id=uuid4()))

    assert excinfo.value.status_code == 422
    assert excinfo.value.code == "oauth_app_required"
    assert "MCP_OAUTH_CLIENT_ID" not in excinfo.value.detail
    auth_create.assert_not_awaited()


@pytest.mark.asyncio
async def test_authorize_answers_a_failed_discovery_with_502(monkeypatch):
    instance = _patch_instance_lookup(monkeypatch)
    _patch_discovery(monkeypatch, MCPOAuthDiscoveryError("no metadata"))

    with pytest.raises(HTTPException) as excinfo:
        await _authorize(OAuthAuthorizeRequest(instance_id=instance.id))

    assert excinfo.value.status_code == 502


@pytest.mark.asyncio
@pytest.mark.flow(MainFlow.MCP_OAUTH)
@pytest.mark.parametrize("credential_source", ["inline", "workspace_secrets"])
async def test_authorize_with_a_custom_oauth_app_keeps_the_secret_out_of_state(
    monkeypatch, credential_source
):
    """A workspace's own OAuth app is persisted on an auth config before the
    redirect, so the OAuth state carries a reference and never a client secret."""
    instance = _patch_instance_lookup(monkeypatch)
    _patch_discovery(monkeypatch, _google_metadata())
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
        get_for_use=AsyncMock(side_effect=[client_id_secret, client_secret_secret]),
        add_reference=AsyncMock(),
    )
    auth_create, stored_state = _patch_authorize(monkeypatch, secret_manager=workspace_manager)
    auth_config_id = auth_create.return_value.id

    if credential_source == "inline":
        body = OAuthAuthorizeRequest(
            instance_id=instance.id,
            credential_mode="custom",
            client_id="inline-client-id",
            client_secret="inline-client-secret",  # noqa: S106  # pragma: allowlist secret
        )
    else:
        body = OAuthAuthorizeRequest(
            instance_id=instance.id,
            credential_mode="custom",
            client_id_secret_id=client_id_secret.id,
            client_secret_secret_id=client_secret_secret.id,
        )

    response = await _authorize(body, secret_catalog)

    query = _query(response.authorize_url)
    expected_client_id = {
        "inline": "inline-client-id",
        "workspace_secrets": "workspace-client-id",  # pragma: allowlist secret
    }[credential_source]
    assert query["client_id"] == [expected_client_id]
    assert query["redirect_uri"] == [_CALLBACK]
    assert _GMAIL_SCOPES[0] in query["scope"][0]
    assert query["code_challenge_method"] == ["S256"]
    assert response.connection_id == instance.id

    config = auth_create.await_args.kwargs["config"]
    assert config["credential_mode"] == "custom"
    # Minted for this instance, so it is deleted with it.
    assert auth_create.await_args.kwargs["mcp_instance_id"] == instance.id
    assert auth_create.await_args.kwargs["openapi_connection_id"] is None
    if credential_source == "inline":
        assert config["client_id"] == "inline-client-id"
        assert auth_create.await_args.kwargs["credentials"] == {  # pragma: allowlist secret
            "client_secret": "inline-client-secret"  # pragma: allowlist secret
        }
        secret_catalog.add_reference.assert_not_awaited()
    else:
        assert auth_create.await_args.kwargs["credentials"] == {}
        assert "client_id" not in config
        assert config["client_id_secret_name"] == "gmail_client_id"  # noqa: S105
        assert config["client_secret_secret_name"] == "gmail_client_secret"  # noqa: S105  # pragma: allowlist secret
        assert secret_catalog.add_reference.await_args_list == [
            call(client_id_secret.id, "mcp_auth_config", str(auth_config_id), "client_id"),
            call(client_secret_secret.id, "mcp_auth_config", str(auth_config_id), "client_secret"),
        ]

    state: OAuthState = stored_state.await_args.args[1]
    assert "secret" not in json.dumps(vars(state))
    assert state.auth_config_id == str(auth_config_id)
    assert state.target_kind == "mcp_instance"
    assert state.connection_id == str(instance.id)


@pytest.mark.asyncio
@pytest.mark.flow(MainFlow.MCP_OAUTH)
async def test_authorize_refuses_another_members_secret_as_the_client_id(monkeypatch):
    """The client ID is echoed back inside the authorize URL, so selecting
    someone else's secret here would hand its plaintext to the caller."""
    register_singleton(AuthorizationService, WorkspaceScopedAuthorizationService())
    instance = _patch_instance_lookup(monkeypatch)
    _patch_discovery(monkeypatch, _google_metadata())
    member_b = UserContext(user_id="member-b", workspace_id="ws", admin_workspaces=[])
    secret = SimpleNamespace(
        id=uuid4(),
        secret_name="member_a_stripe_key",  # noqa: S106  # pragma: allowlist secret
        owner_type=None,
        owner_id=None,
        created_by="member-a",
    )
    session = AsyncMock()
    session.execute.return_value = SimpleNamespace(scalar_one_or_none=lambda: secret)
    workspace_manager = SimpleNamespace(get_secret=AsyncMock(return_value="sk-live-member-a"))
    auth_create, stored_state = _patch_authorize(monkeypatch, secret_manager=workspace_manager)

    with pytest.raises(HTTPException) as exc_info:
        await _authorize(
            OAuthAuthorizeRequest(
                instance_id=instance.id,
                credential_mode="custom",
                client_id_secret_id=secret.id,
                client_secret="typed-secret",  # noqa: S106  # pragma: allowlist secret
            ),
            SecretCatalogService(session, member_b, workspace_manager),
            user_context=member_b,
        )

    assert exc_info.value.status_code == 403
    assert "sk-live-member-a" not in str(exc_info.value.detail)
    workspace_manager.get_secret.assert_not_awaited()
    auth_create.assert_not_awaited()
    stored_state.assert_not_awaited()


def _patch_registration(monkeypatch, client_id="dcr-client-id", client_secret=None):
    register = AsyncMock(
        return_value=SimpleNamespace(client_id=client_id, client_secret=client_secret)
    )
    monkeypatch.setattr(MCPOAuthClientService, "register_client", register)
    return register


@pytest.mark.asyncio
async def test_authorize_persists_dcr_credentials_before_redirecting(monkeypatch):
    """Dynamically registered credentials are needed again at token exchange and
    refresh, so they belong on the auth config, not in expiring state."""
    instance = _patch_instance_lookup(monkeypatch)
    _patch_discovery(
        monkeypatch, _google_metadata(registration_endpoint="https://as.example.com/register")
    )
    auth_create, _ = _patch_authorize(monkeypatch)
    _patch_registration(monkeypatch, client_secret="dcr-secret")  # noqa: S106  # pragma: allowlist secret

    response = await _authorize(OAuthAuthorizeRequest(instance_id=instance.id))

    assert _query(response.authorize_url)["client_id"] == ["dcr-client-id"]
    auth_kwargs = auth_create.await_args.kwargs
    assert auth_kwargs["config"]["client_id"] == "dcr-client-id"
    assert auth_kwargs["config"]["credential_mode"] == "dynamic"
    assert auth_kwargs["credentials"]["client_secret"] == "dcr-secret"  # pragma: allowlist secret


@pytest.mark.asyncio
@pytest.mark.flow(MainFlow.MCP_OAUTH)
async def test_a_reconnect_registers_a_new_client_for_the_current_callback(monkeypatch):
    """A client registered before the callback moved pinned the old redirect URI.
    Every authorize registers afresh with the one this deployment answers at, so
    an already-connected instance (Sentry, say) reconnects without a stale client."""
    instance = _patch_instance_lookup(monkeypatch, auth_config_id=uuid4())
    _patch_discovery(
        monkeypatch, _google_metadata(registration_endpoint="https://as.example.com/register")
    )
    _patch_authorize(monkeypatch)
    register = _patch_registration(monkeypatch)

    response = await _authorize(OAuthAuthorizeRequest(instance_id=instance.id))

    register.assert_awaited_once_with("https://as.example.com/register", _CALLBACK)
    assert _query(response.authorize_url)["redirect_uri"] == [_CALLBACK]


@pytest.mark.asyncio
@pytest.mark.flow(MainFlow.MCP_OAUTH)
async def test_authorize_adds_the_params_the_catalog_spec_declares(monkeypatch):
    """Google issues a refresh token only for access_type=offline; the catalog
    spec says so, the OAuth client carries no per-provider table."""
    instance = _patch_instance_lookup(
        monkeypatch,
        spec_metadata={
            "agentarea:oauth_authorize_params": {"access_type": "offline", "prompt": "consent"}
        },
    )
    _patch_discovery(
        monkeypatch, _google_metadata(registration_endpoint="https://as.example.com/register")
    )
    _patch_authorize(monkeypatch)
    _patch_registration(monkeypatch)

    response = await _authorize(OAuthAuthorizeRequest(instance_id=instance.id))

    query = _query(response.authorize_url)
    assert query["access_type"] == ["offline"]
    assert query["prompt"] == ["consent"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "declared",
    [{"access_type": 1}, {"client_id": "someone-else"}, "access_type=offline"],
)
async def test_authorize_refuses_a_spec_with_malformed_authorize_params(monkeypatch, declared):
    instance = _patch_instance_lookup(
        monkeypatch, spec_metadata={"agentarea:oauth_authorize_params": declared}
    )
    _patch_discovery(
        monkeypatch, _google_metadata(registration_endpoint="https://as.example.com/register")
    )

    with pytest.raises(HTTPException) as exc_info:
        await _authorize(OAuthAuthorizeRequest(instance_id=instance.id))

    assert exc_info.value.status_code == 502
    assert "oauth_authorize_params" in str(exc_info.value.detail)


def _dcr_refused(status_code: int = 400) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://api.instantly.ai/oauth/register")
    return httpx.HTTPStatusError(
        f"Client error '{status_code}'",
        request=request,
        response=httpx.Response(status_code, request=request),
    )


@pytest.mark.asyncio
@pytest.mark.flow(MainFlow.MCP_OAUTH)
async def test_a_refused_registration_answers_with_the_oauth_app_required_code(monkeypatch):
    """The UI switches to the key form on this code, so it reaches the client
    as the problem's ``code``."""
    instance = _patch_instance_lookup(monkeypatch, remote_url="https://mcp.instantly.ai/mcp")
    _patch_discovery(
        monkeypatch,
        AuthServerMetadata(
            issuer="https://api.instantly.ai",
            authorization_endpoint="https://api.instantly.ai/oauth/authorize",
            token_endpoint="https://api.instantly.ai/oauth/token",  # noqa: S106
            registration_endpoint="https://api.instantly.ai/oauth/register",
        ),
    )
    _patch_authorize(monkeypatch)
    monkeypatch.setattr(
        MCPOAuthClientService, "register_client", AsyncMock(side_effect=_dcr_refused())
    )

    with pytest.raises(AppError) as excinfo:
        await _authorize(OAuthAuthorizeRequest(instance_id=instance.id))

    assert excinfo.value.status_code == 422
    assert excinfo.value.code == "oauth_app_required"
    assert excinfo.value.extra == {"issuer": "https://api.instantly.ai"}
    assert "api.instantly.ai" in excinfo.value.detail


# ---------------------------------------------------------------------------
# Platform OAuth apps — one-click Connect through the operator's app
# ---------------------------------------------------------------------------

_GITHUB_MCP_URL = "https://api.githubcopilot.com/mcp/"
_GITHUB_ISSUER = "https://github.com/login/oauth"


def _github_metadata(registration_endpoint: str | None = None) -> AuthServerMetadata:
    """What discovery reports for GitHub — including a token endpoint the
    platform app must override, as a workspace-controlled server could advertise."""
    return AuthServerMetadata(
        issuer=_GITHUB_ISSUER,
        authorization_endpoint="https://github.com/login/oauth/authorize",
        token_endpoint="https://token-thief.example/token",  # noqa: S106
        registration_endpoint=registration_endpoint,
        scopes_supported=["repo"],
        resource="https://api.githubcopilot.com/mcp",
    )


def _github_app(**overrides) -> dict:
    return {
        "issuer": _GITHUB_ISSUER,
        "client_id": "Iv1.platform",
        "client_secret": "platform-secret",  # pragma: allowlist secret
        "authorization_endpoint": "https://github.com/login/oauth/authorize",
        "token_endpoint": "https://github.com/login/oauth/access_token",
        "resource_origins": ["https://api.githubcopilot.com"],
        **overrides,
    }


@pytest.mark.asyncio
@pytest.mark.flow(MainFlow.MCP_OAUTH)
async def test_preflight_names_the_platform_app_as_the_credential_source(
    monkeypatch, platform_apps
):
    _patch_instance_lookup(monkeypatch, remote_url=_GITHUB_MCP_URL)
    _patch_discovery(monkeypatch, _github_metadata())
    platform_apps.append(_github_app())

    result = await _preflight(server_id=uuid4())

    assert result.status == "ready"
    assert result.credential_source == "platform"
    assert result.issuer == _GITHUB_ISSUER
    assert "platform-secret" not in result.model_dump_json()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "app",
    [
        None,
        _github_app(resource_origins=["https://mcp.other.example"]),
        _github_app(issuer="https://github.com/login-oauth"),
    ],
    ids=["no-app", "origin-not-served", "other-issuer"],
)
async def test_preflight_still_requires_an_oauth_app_when_no_platform_app_serves_the_url(
    monkeypatch, platform_apps, app
):
    _patch_instance_lookup(monkeypatch, remote_url=_GITHUB_MCP_URL)
    _patch_discovery(monkeypatch, _github_metadata())
    if app is not None:
        platform_apps.append(app)

    result = await _preflight(instance_id=uuid4())

    assert result.status == "oauth_app_required"


@pytest.mark.asyncio
@pytest.mark.flow(MainFlow.MCP_OAUTH)
@pytest.mark.parametrize("registration_endpoint", [None, "https://github.com/register"])
async def test_authorize_uses_the_configured_platform_app_first(
    monkeypatch, platform_apps, registration_endpoint
):
    """The platform app comes before DCR. The auth config names it by issuer and
    takes its endpoints from it: a discovery answer pointing elsewhere must not
    receive the platform secret, and the workspace never holds the app's credentials."""
    instance = _patch_instance_lookup(monkeypatch, remote_url=_GITHUB_MCP_URL)
    _patch_discovery(monkeypatch, _github_metadata(registration_endpoint))
    platform_apps.append(_github_app())
    auth_create, stored_state = _patch_authorize(monkeypatch)
    register = _patch_registration(monkeypatch)

    response = await _authorize(OAuthAuthorizeRequest(instance_id=instance.id))

    authorize_url = urllib.parse.urlparse(response.authorize_url)
    assert f"{authorize_url.scheme}://{authorize_url.netloc}{authorize_url.path}" == (
        "https://github.com/login/oauth/authorize"
    )
    assert _query(response.authorize_url)["client_id"] == ["Iv1.platform"]
    register.assert_not_awaited()
    auth_kwargs = auth_create.await_args.kwargs
    config = auth_kwargs["config"]
    assert config["token_url"] == "https://github.com/login/oauth/access_token"  # noqa: S105
    assert config["credential_mode"] == "managed"
    assert config["platform_oauth_issuer"] == _GITHUB_ISSUER
    assert "client_id" not in config
    assert auth_kwargs["credentials"] == {}
    assert "platform-secret" not in json.dumps(vars(stored_state.await_args.args[1]))


def _counted(monkeypatch) -> list[dict[str, str]]:
    """Every ``oauth_connect`` count, as its labels."""
    counted: list[dict[str, str]] = []
    monkeypatch.setattr(service, "count", lambda _name, **labels: counted.append(labels))
    return counted


@pytest.mark.asyncio
async def test_analytics_names_the_provider_of_a_configured_platform_app(
    monkeypatch, platform_apps
):
    instance = _patch_instance_lookup(monkeypatch, remote_url=_GITHUB_MCP_URL)
    _patch_discovery(monkeypatch, _github_metadata())
    platform_apps.append(_github_app())
    _patch_authorize(monkeypatch)
    counted = _counted(monkeypatch)

    await _authorize(OAuthAuthorizeRequest(instance_id=instance.id))

    assert counted == [{"provider": "github.com", "outcome": "started"}]


def _internal_metadata() -> AuthServerMetadata:
    return AuthServerMetadata(
        issuer="https://sso.corp.acme.internal",
        authorization_endpoint="https://sso.corp.acme.internal/authorize",
        token_endpoint="https://sso.corp.acme.internal/token",  # noqa: S106
        registration_endpoint="https://sso.corp.acme.internal/register",
        scopes_supported=[],
        resource="https://mcp.corp.acme.internal/mcp",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("platform_app", [False, True], ids=["dcr", "platform-app"])
async def test_analytics_counts_an_internal_authorization_server_as_custom(
    monkeypatch, platform_apps, platform_app
):
    """Only a public provider is named: an internal host stays unnamed even when the
    operator configured it as a platform app."""
    instance = _patch_instance_lookup(monkeypatch, remote_url="https://mcp.corp.acme.internal/mcp")
    _patch_discovery(monkeypatch, _internal_metadata())
    if platform_app:
        platform_apps.append(
            {
                "issuer": "https://sso.corp.acme.internal",
                "client_id": "internal",
                "client_secret": "internal-secret",  # pragma: allowlist secret
                "authorization_endpoint": "https://sso.corp.acme.internal/authorize",
                "token_endpoint": "https://sso.corp.acme.internal/token",
                "resource_origins": ["https://mcp.corp.acme.internal"],
            }
        )
    _patch_authorize(monkeypatch)
    _patch_registration(monkeypatch)
    counted = _counted(monkeypatch)

    await _authorize(OAuthAuthorizeRequest(instance_id=instance.id))

    assert counted == [{"provider": "custom", "outcome": "started"}]


@pytest.mark.asyncio
async def test_a_custom_app_overrides_the_platform_app(monkeypatch, platform_apps):
    instance = _patch_instance_lookup(monkeypatch, remote_url=_GITHUB_MCP_URL)
    _patch_discovery(monkeypatch, _github_metadata())
    platform_apps.append(_github_app())
    auth_create, _ = _patch_authorize(monkeypatch)

    response = await _authorize(
        OAuthAuthorizeRequest(
            instance_id=instance.id,
            credential_mode="custom",
            client_id="own-app",
            client_secret="own-secret",  # noqa: S106  # pragma: allowlist secret
        )
    )

    assert _query(response.authorize_url)["client_id"] == ["own-app"]
    config = auth_create.await_args.kwargs["config"]
    assert config["credential_mode"] == "custom"
    assert "platform_oauth_issuer" not in config
    # The custom app's secret goes to the discovered endpoint, never the platform's.
    assert config["token_url"] == "https://token-thief.example/token"  # noqa: S105


# ---------------------------------------------------------------------------
# Catalog API templates (OpenAPI connections)
# ---------------------------------------------------------------------------

_YANDEX_APP = {
    "issuer": "https://oauth.example.com",
    "client_id": "platform-client-id",
    "client_secret": "platform-client-secret",  # pragma: allowlist secret
    "authorization_endpoint": "https://oauth.example.com/authorize",
    "token_endpoint": "https://oauth.example.com/token",
    "resource_origins": ["https://api-metrika.yandex.net"],
}


def _metrica_oauth() -> dict:
    return {
        "provider_key": "yandex-metrica",
        "authorization_url": "https://oauth.example.com/authorize",
        "token_url": "https://oauth.example.com/token",
        "allowed_api_origins": ["https://api-metrika.yandex.net"],
        "scopes": ["metrika:read"],
        "authorization_scheme": "OAuth",
        "client_auth_method": "client_secret_post",
        "authorize_params": {"access_type": "offline", "prompt": "consent"},
    }


def _metrica_item(**spec_over) -> SimpleNamespace:
    return SimpleNamespace(
        registry_id=uuid4(),
        name="Yandex Metrica",
        description="Read-only analytics",
        spec={
            "connection_type": "openapi",
            "base_url": "https://api-metrika.yandex.net",
            "spec_content": {"openapi": "3.1.0", "paths": {}},
            "oauth": _metrica_oauth(),
            **spec_over,
        },
    )


def _patch_catalog(monkeypatch, item, registry=None):
    registry = registry or SimpleNamespace(registry_type="mcp_servers", is_active=True)

    class _ItemRepository:
        def __init__(self, *_args, **_kwargs):
            pass

        async def get_by_id(self, _requested_id):
            return item

    class _RegistryRepository:
        def __init__(self, *_args, **_kwargs):
            pass

        async def get_by_id(self, _requested_id):
            return registry

    monkeypatch.setattr(targets, "RegistryItemRepository", _ItemRepository)
    monkeypatch.setattr(targets, "RegistryRepository", _RegistryRepository)
    monkeypatch.setattr(targets, "validate_url", lambda *_args, **_kwargs: None)


def _patch_connection_creation(monkeypatch):
    connection_create = AsyncMock(return_value=SimpleNamespace(id=uuid4()))

    class _ConnectionService:
        def __init__(self, *_args, **_kwargs):
            pass

        create_connection = connection_create

    monkeypatch.setattr(targets, "OpenAPIConnectionService", _ConnectionService)
    monkeypatch.setattr(targets, "RepositoryFactory", lambda *_args: object())
    monkeypatch.setattr(
        targets, "build_auth_config_access_checker", lambda *_args, **_kwargs: AsyncMock()
    )
    monkeypatch.setattr(targets, "build_owned_auth_releaser", lambda *_args, **_kwargs: AsyncMock())
    monkeypatch.setattr(targets, "get_real_secret_manager", lambda **_kwargs: SimpleNamespace())
    return connection_create


@pytest.mark.parametrize(
    "authorize_params",
    [{"scope": "everything"}, {"redirect_uri": "https://evil.test"}, {"access_type": 1}, "x"],
)
def test_a_catalog_template_may_not_set_params_the_flow_owns(monkeypatch, authorize_params):
    monkeypatch.setattr(targets, "validate_url", lambda *_args, **_kwargs: None)
    oauth = {**_metrica_oauth(), "authorize_params": authorize_params}

    with pytest.raises(HTTPException, match="Invalid OAuth authorize params"):
        targets.catalog_oauth_profile({"oauth": oauth})


@pytest.mark.asyncio
async def test_catalog_preflight_is_ready_through_the_platform_app(monkeypatch, platform_apps):
    _patch_catalog(monkeypatch, _metrica_item())
    platform_apps.append(_YANDEX_APP)

    result = await _preflight(catalog_item_id=uuid4())

    assert result.status == "ready"
    assert result.credential_source == "platform"
    assert result.redirect_uri == _CALLBACK
    assert "platform-client" not in result.model_dump_json()


@pytest.mark.asyncio
async def test_catalog_preflight_asks_for_an_oauth_app_when_the_platform_has_none(monkeypatch):
    _patch_catalog(monkeypatch, _metrica_item())

    result = await _preflight(catalog_item_id=uuid4())

    assert result.status == "oauth_app_required"
    assert result.credential_source is None
    assert "redirect URI" in result.detail
    assert result.redirect_uri == _CALLBACK


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mismatch",
    [
        # The client secret would go to a token endpoint the operator never named.
        {"token_endpoint": "https://oauth.example.test/token"},
        {"authorization_endpoint": "https://oauth.example.test/authorize"},
        # Tokens minted through the app may not reach the template's API.
        {"resource_origins": ["https://api.webmaster.yandex.net"]},
    ],
)
async def test_catalog_preflight_ignores_a_platform_app_that_does_not_match(
    monkeypatch, platform_apps, mismatch
):
    _patch_catalog(monkeypatch, _metrica_item())
    platform_apps.append({**_YANDEX_APP, **mismatch})

    result = await _preflight(catalog_item_id=uuid4())

    assert result.status == "oauth_app_required"


@pytest.mark.asyncio
async def test_catalog_preflight_404s_for_an_unknown_item(monkeypatch):
    _patch_catalog(monkeypatch, None)

    with pytest.raises(HTTPException) as exc_info:
        await _preflight(catalog_item_id=uuid4())

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_catalog_preflight_rejects_an_item_that_is_not_an_api_connection(monkeypatch):
    _patch_catalog(monkeypatch, _metrica_item(connection_type="mcp"))

    with pytest.raises(HTTPException) as exc_info:
        await _preflight(catalog_item_id=uuid4())

    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
@pytest.mark.parametrize("credential_source", ["platform", "inline", "workspace_secrets"])
async def test_catalog_authorize_creates_the_connection_and_keeps_secrets_out_of_state(
    monkeypatch, platform_apps, credential_source
):
    item_id = uuid4()
    _patch_catalog(monkeypatch, _metrica_item())
    platform_apps.append(_YANDEX_APP)
    connection_create = _patch_connection_creation(monkeypatch)
    connection_id = connection_create.return_value.id
    client_id_secret = SimpleNamespace(
        id=uuid4(),
        secret_name="metrika_client_id",  # noqa: S106  # pragma: allowlist secret
        owner_type=None,
    )
    client_secret_secret = SimpleNamespace(
        id=uuid4(),
        secret_name="metrika_client_secret",  # noqa: S106  # pragma: allowlist secret
        owner_type=None,
    )
    workspace_manager = SimpleNamespace(
        get_secret=AsyncMock(
            side_effect=lambda name: {
                "metrika_client_id": "workspace-client-id",
                "metrika_client_secret": "workspace-client-secret",  # pragma: allowlist secret
            }.get(name)
        )
    )
    secret_catalog = SimpleNamespace(
        get_for_use=AsyncMock(side_effect=[client_id_secret, client_secret_secret]),
        add_reference=AsyncMock(),
    )
    auth_create, stored_state = _patch_authorize(monkeypatch, secret_manager=workspace_manager)
    auth_config_id = auth_create.return_value.id

    if credential_source == "platform":
        body = OAuthAuthorizeRequest(catalog_item_id=item_id, return_to=_APP)
    elif credential_source == "inline":
        body = OAuthAuthorizeRequest(
            catalog_item_id=item_id,
            credential_mode="custom",
            client_id="inline-client-id",
            client_secret="inline-client-secret",  # noqa: S106  # pragma: allowlist secret
            return_to=_APP,
        )
    else:
        body = OAuthAuthorizeRequest(
            catalog_item_id=item_id,
            credential_mode="custom",
            client_id_secret_id=client_id_secret.id,
            client_secret_secret_id=client_secret_secret.id,
            return_to=_APP,
        )

    response = await _authorize(body, secret_catalog)

    assert response.connection_id == connection_id
    assert connection_create.await_args.kwargs["registry_item_id"] == item_id
    assert connection_create.await_args.kwargs["status"] == "pending"
    query = _query(response.authorize_url)
    assert response.authorize_url.startswith("https://oauth.example.com/authorize?")
    assert query["client_id"] == [
        {
            "platform": "platform-client-id",
            "inline": "inline-client-id",
            "workspace_secrets": "workspace-client-id",  # pragma: allowlist secret
        }[credential_source]
    ]
    assert query["redirect_uri"] == [_CALLBACK]
    assert query["scope"] == ["metrika:read"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["access_type"] == ["offline"]
    assert query["prompt"] == ["consent"]
    assert "resource" not in query

    config = auth_create.await_args.kwargs["config"]
    assert config["provider"] == "yandex-metrica"
    # Minted for this connection, so it is deleted with it.
    assert auth_create.await_args.kwargs["openapi_connection_id"] == connection_id
    assert auth_create.await_args.kwargs["mcp_instance_id"] is None
    assert config["authorization_scheme"] == "OAuth"
    if credential_source == "platform":
        assert auth_create.await_args.kwargs["credentials"] == {}
        assert config["credential_mode"] == "managed"
        assert config["platform_oauth_issuer"] == "https://oauth.example.com"
        assert "client_id" not in config
        assert "platform-client-secret" not in json.dumps(config)
        secret_catalog.add_reference.assert_not_awaited()
    elif credential_source == "inline":
        assert config["client_id"] == "inline-client-id"
        assert auth_create.await_args.kwargs["credentials"] == {  # pragma: allowlist secret
            "client_secret": "inline-client-secret"  # pragma: allowlist secret
        }
    else:
        assert config["client_id_secret_name"] == "metrika_client_id"  # noqa: S105
        assert secret_catalog.add_reference.await_args_list == [
            call(client_id_secret.id, "mcp_auth_config", str(auth_config_id), "client_id"),
            call(client_secret_secret.id, "mcp_auth_config", str(auth_config_id), "client_secret"),
        ]
    state: OAuthState = stored_state.await_args.args[1]
    assert state.target_kind == "openapi_connection"
    assert state.connection_id == str(connection_id)
    assert "secret" not in json.dumps(vars(state))


@pytest.mark.asyncio
async def test_catalog_authorize_without_a_platform_app_asks_for_one(monkeypatch):
    """No operator app is the same answer as for an MCP server: bring your own."""
    _patch_catalog(monkeypatch, _metrica_item())
    connection_create = _patch_connection_creation(monkeypatch)
    _patch_authorize(monkeypatch)

    with pytest.raises(AppError) as excinfo:
        await _authorize(OAuthAuthorizeRequest(catalog_item_id=uuid4()))

    assert excinfo.value.code == "oauth_app_required"
    connection_create.assert_not_awaited()


# ---------------------------------------------------------------------------
# The callback — one for every kind, dispatching on the state's target
# ---------------------------------------------------------------------------

_INSTANCE_ID = "d50241d7-eafe-4011-8479-b40f7a2aab3c"
_CONNECT_PAGE = f"{_APP}/w/acme/connect/{_INSTANCE_ID}"


def _flow(**overrides) -> OAuthState:
    return OAuthState(
        **{
            "target_kind": "mcp_instance",
            "connection_id": _INSTANCE_ID,
            "auth_config_id": str(uuid4()),
            "workspace_id": "ws-1",
            "user_id": "user-1",
            "code_verifier": "verifier",
            "return_to": "",
            **overrides,
        }
    )


class _Callback:
    """The callback's and the finish's collaborators, faked; records what they parked and attached."""

    def __init__(
        self, monkeypatch, flow: OAuthState | None, *, exchange=None, auth_config=None
    ):
        self.flow = flow
        self.parked: list[tuple[str, ReturnedFlow]] = []
        self.exchange = exchange or AsyncMock()
        self.auth_config = SimpleNamespace(id=uuid4(), config=auth_config or {})
        self.instance_update = AsyncMock()
        self.connection_update = AsyncMock(return_value=SimpleNamespace())
        self.after_connect = []
        test = self

        class _AuthService:
            def __init__(self, *_args, **_kwargs):
                pass

            get = AsyncMock(return_value=test.auth_config)
            complete_authorization = test.exchange

        class _InstanceRepository:
            def __init__(self, *_args, **_kwargs):
                pass

            update = test.instance_update

        class _ConnectionRepository:
            def __init__(self, *_args, **_kwargs):
                pass

            update = test.connection_update

        monkeypatch.setattr(oauth_state, "pop", AsyncMock(return_value=flow))

        async def _store_returned(token: str, returned: ReturnedFlow) -> None:
            self.parked.append((token, returned))

        monkeypatch.setattr(oauth_state, "store_returned", _store_returned)

        async def _pop_returned(token: str) -> ReturnedFlow | None:
            for i, (parked_token, returned) in enumerate(self.parked):
                if parked_token == token:
                    del self.parked[i]
                    return returned
            return None

        monkeypatch.setattr(oauth_state, "pop_returned", _pop_returned)
        monkeypatch.setattr(service, "workspace_slug_for", AsyncMock(return_value="acme"))
        monkeypatch.setattr(service, "get_real_secret_manager", lambda **_kwargs: SimpleNamespace())
        monkeypatch.setattr(service, "MCPAuthService", _AuthService)
        monkeypatch.setattr(targets, "MCPServerInstanceRepository", _InstanceRepository)
        monkeypatch.setattr(targets, "OpenAPIConnectionRepository", _ConnectionRepository)
        monkeypatch.setattr(
            service, "after_connect", lambda state, _uc: self.after_connect.append(state)
        )

    async def run(self, *, code="code", state="state", error=None, error_description=None):
        response = await routes.oauth_callback(
            code=code,
            state=state,
            error=error,
            error_description=error_description,
        )
        assert response.status_code == 302
        return response.headers["location"]

    async def finish(self, *, user_id="user-1", token=None, reachable=("ws-1",)):
        """Finish the flow the provider sent back; the callback runs first unless a token is given."""
        if token is None:
            location = await self.run()
            token = urllib.parse.parse_qs(urllib.parse.urlparse(location).query)["token"][0]
        response = await routes.oauth_finish(
            body=OAuthFinishRequest(token=token),
            principal=SimpleNamespace(user_id=user_id, accessible_workspaces=list(reachable)),
            db_session=AsyncMock(),
        )
        return response.location


@pytest.mark.asyncio
@pytest.mark.flow(MainFlow.MCP_OAUTH)
async def test_finishing_attaches_the_credential_to_the_mcp_instance(monkeypatch):
    flow = _flow()
    callback = _Callback(monkeypatch, flow)

    location = await callback.finish()

    assert location == f"{_APP}/w/acme/connections/{_INSTANCE_ID}?oauth=success"
    callback.exchange.assert_awaited_once_with(
        callback.auth_config, code="code", redirect_uri=_CALLBACK, code_verifier="verifier"
    )
    callback.instance_update.assert_awaited_once()
    assert callback.instance_update.await_args.kwargs == {"auth_config_id": callback.auth_config.id}
    callback.connection_update.assert_not_awaited()
    assert callback.after_connect == [flow]


@pytest.mark.asyncio
async def test_the_callback_parks_the_code_and_sends_the_browser_to_finish(monkeypatch):
    flow = _flow(return_to=_CONNECT_PAGE)
    callback = _Callback(monkeypatch, flow)

    location = urllib.parse.urlparse(await callback.run())

    assert (location.scheme, location.netloc, location.path) == (
        "https",
        "app.agentarea.ai",
        "/oauth/finish",
    )
    token = urllib.parse.parse_qs(location.query)["token"][0]
    assert callback.parked == [(token, ReturnedFlow(flow=flow, code="code"))]
    callback.exchange.assert_not_awaited()
    callback.instance_update.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.flow(MainFlow.MCP_OAUTH)
async def test_a_sign_in_url_followed_by_someone_else_attaches_nothing(monkeypatch):
    """RFC 6749 §10.12: an authorize URL sent to another person must not put
    their account into the sender's connection."""
    callback = _Callback(monkeypatch, _flow(user_id="sender"))
    token = urllib.parse.parse_qs(urllib.parse.urlparse(await callback.run()).query)["token"][0]

    with pytest.raises(HTTPException) as refused:
        await callback.finish(user_id="recipient", token=token)
    # The refusal is final: the sender cannot redeem the recipient's code after it.
    with pytest.raises(HTTPException) as retried:
        await callback.finish(user_id="sender", token=token)

    assert (refused.value.status_code, retried.value.status_code) == (403, 400)
    callback.exchange.assert_not_awaited()
    callback.instance_update.assert_not_awaited()
    callback.connection_update.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_starter_who_no_longer_reaches_the_workspace_cannot_finish(monkeypatch):
    """Removed from it while at the provider, or holding a key issued for another one."""
    callback = _Callback(monkeypatch, _flow())

    with pytest.raises(HTTPException) as excinfo:
        await callback.finish(reachable=["ws-other"])

    assert excinfo.value.status_code == 403
    callback.exchange.assert_not_awaited()


@pytest.mark.asyncio
async def test_an_unknown_finish_token_is_refused(monkeypatch):
    callback = _Callback(monkeypatch, None)

    with pytest.raises(HTTPException) as excinfo:
        await callback.finish(token="replayed")

    assert excinfo.value.status_code == 400
    callback.exchange.assert_not_awaited()


@pytest.mark.asyncio
async def test_finishing_activates_the_api_connection(monkeypatch):
    connection_id = str(uuid4())
    callback = _Callback(
        monkeypatch, _flow(target_kind="openapi_connection", connection_id=connection_id)
    )

    location = await callback.finish()

    assert location == f"{_APP}/w/acme/connections/openapi/{connection_id}?oauth=success"
    assert callback.connection_update.await_args.kwargs == {
        "auth_config_id": callback.auth_config.id,
        "status": "active",
    }
    callback.instance_update.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["token_exchange_failed", "no_access_token"])
async def test_a_failed_exchange_lands_with_the_reason_and_attaches_nothing(monkeypatch, reason):
    callback = _Callback(
        monkeypatch,
        _flow(return_to=_CONNECT_PAGE),
        exchange=AsyncMock(side_effect=OAuthCodeExchangeError(reason)),
    )

    location = await callback.finish()

    assert location == f"{_CONNECT_PAGE}?oauth=error&reason={reason}"
    callback.instance_update.assert_not_awaited()


@pytest.mark.asyncio
async def test_connect_link_returns_to_the_connect_page_it_started_from(monkeypatch):
    callback = _Callback(monkeypatch, _flow(return_to=_CONNECT_PAGE))

    assert await callback.finish() == f"{_CONNECT_PAGE}?oauth=success"


@pytest.mark.asyncio
async def test_connect_page_query_and_fragment_are_not_carried_back(monkeypatch):
    callback = _Callback(
        monkeypatch, _flow(return_to=f"{_CONNECT_PAGE}?oauth=error&next=https://evil.example#x")
    )

    assert await callback.finish() == f"{_CONNECT_PAGE}?oauth=success"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "return_to",
    [
        f"{_APP}/w/other/connect/{_INSTANCE_ID}",
        f"{_APP}/w/acme/connect/f37e9858-f588-4911-b5bf-ae2f09f8cdbb",
        f"https://evil.example/w/acme/connect/{_INSTANCE_ID}",
        f"{_APP}/w/acme/connect/{_INSTANCE_ID}/../../settings",
        f"{_APP}/w/acme/connect/{_INSTANCE_ID}/extra",
        f"{_APP}/w/acme/agents",
    ],
)
async def test_any_other_return_to_lands_on_the_connection_page(monkeypatch, return_to):
    callback = _Callback(monkeypatch, _flow(return_to=return_to))

    assert await callback.finish() == f"{_APP}/w/acme/connections/{_INSTANCE_ID}?oauth=success"


@pytest.mark.asyncio
async def test_a_denied_sign_in_returns_to_the_connect_page_it_started_from(monkeypatch):
    callback = _Callback(monkeypatch, _flow(return_to=_CONNECT_PAGE))

    location = await callback.run(
        code=None, error="access_denied", error_description="The user denied the request"
    )

    assert location == f"{_CONNECT_PAGE}?oauth=error&reason=The+user+denied+the+request"
    oauth_state.pop.assert_awaited_once_with("state")
    callback.exchange.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_denied_sign_in_without_the_reason_names_the_error(monkeypatch):
    callback = _Callback(monkeypatch, _flow(return_to=_CONNECT_PAGE))

    location = await callback.run(code=None, error="access_denied")

    assert location == f"{_CONNECT_PAGE}?oauth=error&reason=access_denied"


@pytest.mark.asyncio
async def test_a_denied_api_sign_in_lands_on_the_connection(monkeypatch):
    connection_id = str(uuid4())
    callback = _Callback(
        monkeypatch, _flow(target_kind="openapi_connection", connection_id=connection_id)
    )

    location = await callback.run(code=None, error="access_denied")

    assert location == (
        f"{_APP}/w/acme/connections/openapi/{connection_id}?oauth=error&reason=access_denied"
    )
    callback.connection_update.assert_not_awaited()


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
async def test_a_denied_sign_in_without_state_lands_on_the_frontend_root(monkeypatch, description):
    _Callback(monkeypatch, None)

    location = urllib.parse.urlparse(
        await _Callback(monkeypatch, None).run(
            code=None, state=None, error="access_denied", error_description=description
        )
    )

    assert (location.scheme, location.netloc, location.path) == ("https", "app.agentarea.ai", "/")
    assert urllib.parse.parse_qs(location.query) == {"oauth": ["error"], "reason": [description]}


@pytest.mark.asyncio
async def test_an_unknown_state_without_an_error_is_refused(monkeypatch):
    _Callback(monkeypatch, None)

    with pytest.raises(HTTPException) as excinfo:
        await routes.oauth_callback(
            code="code", state="replayed", error=None, error_description=None
        )

    assert excinfo.value.status_code == 400


@pytest.mark.asyncio
@pytest.mark.parametrize("target_kind", ["mcp_instance", "openapi_connection"])
async def test_a_flow_whose_workspace_was_deleted_finishes_on_the_frontend_root(
    monkeypatch, target_kind
):
    callback = _Callback(monkeypatch, _flow(target_kind=target_kind))

    def _gone(workspace_id: str) -> str:
        raise LookupError(f"Workspace {workspace_id} does not exist")

    monkeypatch.setattr(service, "workspace_slug_for", AsyncMock(side_effect=_gone))

    location = urllib.parse.urlparse(await callback.finish())

    assert (location.scheme, location.netloc, location.path) == ("https", "app.agentarea.ai", "/")
    assert urllib.parse.parse_qs(location.query) == {
        "oauth": ["error"],
        "reason": ["workspace_gone"],
    }
    callback.exchange.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_denied_sign_in_whose_workspace_was_deleted_lands_on_the_frontend_root(
    monkeypatch,
):
    callback = _Callback(monkeypatch, _flow())
    monkeypatch.setattr(service, "workspace_slug_for", AsyncMock(side_effect=LookupError("gone")))

    location = urllib.parse.urlparse(await callback.run(code=None, error="access_denied"))

    assert (location.scheme, location.netloc, location.path) == ("https", "app.agentarea.ai", "/")
    assert urllib.parse.parse_qs(location.query) == {
        "oauth": ["error"],
        "reason": ["workspace_gone"],
    }


@pytest.mark.asyncio
async def test_oauth_state_is_consumed_atomically(monkeypatch):
    flow = _flow()
    redis = SimpleNamespace(getdel=AsyncMock(return_value=json.dumps(vars(flow))))
    monkeypatch.setattr(oauth_state, "_redis", AsyncMock(return_value=redis))

    assert await oauth_state.pop("one-time-state") == flow
    redis.getdel.assert_awaited_once_with("oauth_state:one-time-state")


@pytest.mark.asyncio
async def test_a_returned_flow_is_consumed_atomically_by_its_first_finish(monkeypatch):
    stored: dict[str, str] = {}

    async def _set(key, value, ex):
        stored[key] = value

    async def _getdel(key):
        return stored.pop(key, None)

    redis = SimpleNamespace(set=_set, getdel=_getdel)
    monkeypatch.setattr(oauth_state, "_redis", AsyncMock(return_value=redis))
    returned = ReturnedFlow(flow=_flow(), code="code")

    await oauth_state.store_returned("one-time-finish", returned)

    assert list(stored) == ["oauth_returned:one-time-finish"]
    assert await oauth_state.pop_returned("one-time-finish") == returned
    assert await oauth_state.pop_returned("one-time-finish") is None


# ---------------------------------------------------------------------------
# Connect pages and post-connect discovery
# ---------------------------------------------------------------------------


def test_connect_page_url_names_the_workspace_and_instance():
    assert pages.connect_page_url("acme", _INSTANCE_ID) == _CONNECT_PAGE


def test_connect_page_url_fails_loud_without_a_frontend_url(monkeypatch):
    monkeypatch.setattr(
        pages,
        "get_settings",
        lambda: SimpleNamespace(app=SimpleNamespace(APP_URL="", API_URL=_API)),
    )

    with pytest.raises(RuntimeError, match="AGENTAREA_APP_URL"):
        pages.connect_page_url("acme", _INSTANCE_ID)


class _DiscoveryHarness:
    """Runs the post-OAuth discovery task with its collaborators faked, recording sessions."""

    def __init__(self, monkeypatch, discover):
        import agentarea_mcp.application.service as mcp_service

        self.background_session = SimpleNamespace(name="background_session")
        self.service_sessions = []
        self.secret_manager_sessions = []

        @asynccontextmanager
        async def background_session():
            yield self.background_session

        monkeypatch.setattr(
            targets, "get_database", lambda: SimpleNamespace(session=background_session)
        )

        def secret_manager(*, session, user_context):
            self.secret_manager_sessions.append(session)
            return SimpleNamespace()

        monkeypatch.setattr(targets, "get_real_secret_manager", secret_manager)

        def mcp_instance_service(*, repository_factory, event_broker, secret_manager):
            self.service_sessions.append(repository_factory.session)
            return SimpleNamespace(discover_and_store_tools=discover)

        monkeypatch.setattr(mcp_service, "MCPServerInstanceService", mcp_instance_service)


@pytest.mark.flow(MainFlow.MCP_OAUTH)
@pytest.mark.asyncio
async def test_post_oauth_discovery_runs_on_its_own_session(monkeypatch):
    discover = AsyncMock(return_value=True)
    harness = _DiscoveryHarness(monkeypatch, discover)
    instance_id = uuid4()

    await targets.discover_after_oauth(
        UserContext(user_id="user-1", workspace_id="ws-1"), instance_id
    )

    discover.assert_awaited_once_with(instance_id)
    assert harness.service_sessions == [harness.background_session]
    assert harness.secret_manager_sessions == [harness.background_session]


@pytest.mark.asyncio
async def test_post_oauth_discovery_failure_is_logged_with_traceback(monkeypatch, caplog):
    _DiscoveryHarness(monkeypatch, AsyncMock(side_effect=RuntimeError("upstream down")))

    with caplog.at_level(logging.ERROR, logger=targets.logger.name):
        await targets.discover_after_oauth(
            UserContext(user_id="user-1", workspace_id="ws-1"), uuid4()
        )

    assert [r for r in caplog.records if r.exc_info and "discovery" in r.getMessage()], caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("issuer_config", "provider"),
    [
        ({"platform_oauth_issuer": _GITHUB_ISSUER, "credential_mode": "managed"}, "github.com"),
        ({"issuer": _GITHUB_ISSUER, "credential_mode": "custom"}, "github.com"),
        ({"issuer": "https://sso.corp.acme.internal", "credential_mode": "dynamic"}, "custom"),
        ({}, "custom"),
    ],
    ids=["platform-app", "custom-app-for-a-platform-issuer", "unconfigured-issuer", "no-issuer"],
)
async def test_analytics_names_a_completed_flow_by_its_auth_config(
    monkeypatch, platform_apps, issuer_config, provider
):
    platform_apps.append(_github_app())
    callback = _Callback(monkeypatch, _flow(), auth_config=issuer_config)
    counted = _counted(monkeypatch)

    await callback.finish()

    assert counted == [{"provider": provider, "outcome": "succeeded"}]


@pytest.mark.asyncio
async def test_analytics_counts_a_sign_in_finished_by_someone_else(monkeypatch):
    callback = _Callback(monkeypatch, _flow())
    counted = _counted(monkeypatch)

    with pytest.raises(HTTPException):
        await callback.finish(user_id="someone-else")

    assert counted == [{"provider": "unknown", "outcome": "failed:other_user"}]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "outcome"),
    [
        ("access_denied", "failed:access_denied"),
        ("temporarily_unavailable", "failed:temporarily_unavailable"),
        ("evil.example/phish", "failed:other"),
        ("x" * 40, "failed:other"),
    ],
)
@pytest.mark.parametrize("with_state", [True, False], ids=["state", "no-state"])
async def test_analytics_counts_a_provider_error_only_as_an_rfc_6749_code(
    monkeypatch, error, outcome, with_state
):
    """The public callback's ``error`` is attacker-chosen: only the RFC's codes are labels."""
    callback = _Callback(monkeypatch, _flow() if with_state else None)
    counted = _counted(monkeypatch)

    await callback.run(code=None, state="state" if with_state else None, error=error)

    assert counted == [{"provider": "unknown", "outcome": outcome}]
