"""Preflight → authorize → callback, the same for every connection kind.

Which OAuth client signs in is decided once: the workspace's own app when the
caller brings one, else the operator's platform app (AGENTAREA_MCP_OAUTH_APPS),
else a client registered dynamically (RFC 7591), else the caller must bring
one. The code exchange and every later refresh run in ``MCPAuthService``.
"""

import logging
import secrets
import urllib.parse
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

import httpx
from agentarea_common.analytics import count
from agentarea_common.auth.context import UserContext
from agentarea_common.base.tenant_scope import bind_workspace_scope
from agentarea_common.exceptions import AppError
from agentarea_common.workspaces.lookup import workspace_slug_for
from agentarea_mcp.application.auth_service import (
    AuthConfigAccessDeniedError,
    MCPAuthService,
    MissingCredentialsError,
    OAuthCodeExchangeError,
)
from agentarea_mcp.application.oauth_client_service import (
    MCPOAuthClientService,
    MCPOAuthDiscoveryError,
    PKCEPair,
)
from agentarea_mcp.application.oauth_profile import (
    CredentialSource,
    OAuthProfile,
    auto_credential_source,
    platform_app_for,
)
from agentarea_mcp.application.platform_oauth_app import platform_oauth_app
from agentarea_mcp.domain.auth_models import MCPAuthConfig
from agentarea_mcp.infrastructure.auth_repository import MCPAuthConfigRepository
from agentarea_secrets.catalog_service import SecretCatalogService
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from agentarea_api.api.deps.services import get_real_secret_manager
from agentarea_api.api.v1.oauth_app_credentials import (
    CustomOAuthAppFields,
    ResolvedOAuthApp,
    resolve_custom_oauth_app,
)
from agentarea_api.oauth_connect import state as oauth_state
from agentarea_api.oauth_connect.pages import callback_uri, finish_page_url, frontend_base
from agentarea_api.oauth_connect.targets import (
    ConnectTarget,
    NotAuthorizableError,
    PreflightTarget,
    after_connect,
    attach_credential,
    landing_url,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Preflight:
    """Whether Connect can run, and with which client."""

    status: Literal["ready", "oauth_app_required", "unsupported"]
    connected: bool
    credential_source: CredentialSource | Literal["custom"] | None = None
    detail: str = ""
    issuer: str | None = None
    authorization_endpoint: str | None = None
    scopes: tuple[str, ...] = ()
    default_scopes: tuple[str, ...] = ()
    # The connection's own app's client ID, when its config keeps it in plain.
    client_id: str | None = None


@dataclass(frozen=True)
class Authorization:
    authorize_url: str
    connection_id: UUID


#: Public authorization servers analytics may name: the issuer hosts of the providers
#: AgentArea's catalog connects to. Any other host, an internal one included, is
#: never sent.
PUBLIC_ISSUER_HOSTS = frozenset(
    {
        "accounts.google.com",
        "api.notion.com",
        "auth.atlassian.com",
        "github.com",
        "gitlab.com",
        "linear.app",
        "login.microsoftonline.com",
        "login.salesforce.com",
        "oauth.yandex.ru",
        "slack.com",
        "www.canva.com",
        "www.figma.com",
    }
)

#: The ``error`` codes of RFC 6749 §4.1.2.1 and §5.2; anything else a provider sends
#: back is counted as ``other``.
OAUTH_ERROR_CODES = frozenset(
    {
        "invalid_request",
        "unauthorized_client",
        "access_denied",
        "unsupported_response_type",
        "invalid_scope",
        "server_error",
        "temporarily_unavailable",
        "invalid_client",
        "invalid_grant",
        "unsupported_grant_type",
    }
)


def _provider_label(issuer: str | None) -> str:
    """The issuer's host when it is a public provider served by a platform app, else ``custom``."""
    if not issuer or platform_oauth_app(issuer) is None:
        return "custom"
    host = urllib.parse.urlsplit(issuer).hostname
    return host if host in PUBLIC_ISSUER_HOSTS else "custom"


def _auth_config_issuer(config: dict[str, Any]) -> str | None:
    return config.get("platform_oauth_issuer") or config.get("issuer") or None


def _oauth_error(error: str) -> str:
    return error if error in OAUTH_ERROR_CODES else "other"


def _oauth_app_required(detail: str, issuer: str | None) -> AppError:
    return AppError(detail, status_code=422, code="oauth_app_required", extra={"issuer": issuer})


def _own_app(target: PreflightTarget, profile: OAuthProfile) -> MCPAuthConfig | None:
    """The OAuth app the person brought for this connection, when a reconnect may sign in with it.

    Only against the endpoints it was registered with.
    """
    auth_config = target.current_auth_config
    if auth_config is None or auth_config.config.get("credential_mode") != "custom":
        return None
    endpoints = (auth_config.config.get("authorization_url"), auth_config.config.get("token_url"))
    if endpoints != (profile.authorization_endpoint, profile.token_endpoint):
        return None
    return auth_config


async def preflight(target: PreflightTarget) -> Preflight:
    """Every outcome is an answer: "no OAuth here" is rendered, not decoded from an error."""
    try:
        profile = await target.profile()
    except NotAuthorizableError as exc:
        return Preflight(status="unsupported", connected=target.connected, detail=exc.detail)
    own_app = _own_app(target, profile)
    source = "custom" if own_app is not None else auto_credential_source(profile)
    return Preflight(
        status="ready" if source else "oauth_app_required",
        connected=target.connected,
        credential_source=source,
        client_id=own_app.config.get("client_id") if own_app is not None else None,
        detail="" if source else target.oauth_app_required_detail(profile),
        issuer=profile.issuer,
        authorization_endpoint=profile.authorization_endpoint,
        scopes=profile.scopes,
        default_scopes=profile.requested_scopes(None),
    )


class OAuthConnectService:
    """Starts an authorization for the caller, in the caller's workspace."""

    def __init__(
        self,
        session: AsyncSession,
        user_context: UserContext,
        secret_catalog: SecretCatalogService,
    ) -> None:
        self._session = session
        self._user_context = user_context
        self._secret_catalog = secret_catalog

    async def authorize(
        self,
        target: ConnectTarget,
        *,
        credential_mode: Literal["auto", "custom"],
        custom: CustomOAuthAppFields,
        return_to: str,
        scopes: list[str] | None = None,
    ) -> Authorization:
        """``scopes`` is the person's pick among the offered ones; None asks for the default."""
        await target.ensure_may_authorize()
        try:
            profile = await target.profile()
        except NotAuthorizableError as exc:
            count("oauth_connect", provider="unknown", outcome="failed:not_authorizable")
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
        try:
            requested = profile.requested_scopes(scopes)
        except ValueError as exc:
            raise AppError(str(exc), status_code=422, code="invalid_scopes") from exc

        secret_manager = get_real_secret_manager(
            session=self._session, user_context=self._user_context
        )
        auth_service = MCPAuthService(
            MCPAuthConfigRepository(self._session, self._user_context), secret_manager
        )
        own_app = _own_app(target, profile) if credential_mode == "auto" else None
        if own_app is not None:
            # A reconnect signs in again with the client the connection holds:
            # its secret stays where it is, and the callback renews the tokens.
            auth_config, client_id = await self._own_client(auth_service, own_app, profile)
            kind, connection_id = await target.create_connection()
        else:
            if credential_mode == "custom":
                resolved = await resolve_custom_oauth_app(
                    custom, catalog=self._secret_catalog, manager=secret_manager
                )
                resolved.config["credential_mode"] = "custom"
            else:
                profile, resolved = await self._auto_client(target, profile)

            kind, connection_id = await target.create_connection()
            # The client is persisted before the redirect: token exchange and every
            # refresh need it again, so the OAuth state names it instead of carrying it.
            auth_config = await auth_service.create(
                name=target.auth_config_name(connection_id),
                auth_type="oauth2",
                config={
                    "provider": profile.provider,
                    **({"issuer": profile.issuer} if profile.issuer else {}),
                    "authorization_url": profile.authorization_endpoint,
                    "token_url": profile.token_endpoint,
                    "scopes": list(requested),
                    "authorization_scheme": profile.authorization_scheme,
                    "client_auth_method": profile.client_auth_method,
                    **resolved.config,
                },
                credentials=resolved.credentials,
                allow_managed_credentials=True,
                # Minted for this connection, so it is deleted with it.
                mcp_instance_id=connection_id if kind == "mcp_instance" else None,
                openapi_connection_id=connection_id if kind == "openapi_connection" else None,
            )
            for secret_id, field_name in resolved.references:
                await self._secret_catalog.add_reference(
                    secret_id, "mcp_auth_config", str(auth_config.id), field_name
                )
            client_id = resolved.client_id

        pkce = PKCEPair.generate()
        token = secrets.token_urlsafe(32)
        await oauth_state.store(
            token,
            oauth_state.OAuthState(
                target_kind=kind,
                connection_id=str(connection_id),
                auth_config_id=str(auth_config.id),
                workspace_id=str(self._user_context.workspace_id),
                user_id=str(self._user_context.user_id),
                code_verifier=pkce.verifier,
                return_to=return_to,
                scopes=list(requested) if own_app is not None else None,
            ),
        )
        authorize_url = MCPOAuthClientService().build_authorize_url(
            profile,
            client_id=client_id,
            redirect_uri=callback_uri(),
            pkce=pkce,
            state=token,
            scopes=list(requested),
        )
        count("oauth_connect", provider=_provider_label(profile.issuer), outcome="started")
        return Authorization(authorize_url=authorize_url, connection_id=connection_id)

    async def _own_client(
        self, auth_service: MCPAuthService, own_app: MCPAuthConfig, profile: OAuthProfile
    ) -> tuple[MCPAuthConfig, str]:
        """The connection's own app, for whoever may put its credential to use."""
        try:
            auth_config = await auth_service.get_for_use(own_app.id)
        except AuthConfigAccessDeniedError as exc:
            raise HTTPException(
                status_code=403,
                detail=f"{exc} Connect with your own OAuth app instead.",
            ) from exc
        try:
            client_id, _, _ = await auth_service.get_oauth_client_credentials(
                auth_config, require_secret=True
            )
        except MissingCredentialsError as exc:
            logger.warning(
                "Own OAuth app of auth config %s is incomplete: %s",
                auth_config.id,
                exc,
                exc_info=True,
            )
            count(
                "oauth_connect",
                provider=_provider_label(profile.issuer),
                outcome="failed:oauth_app_required",
            )
            raise _oauth_app_required(
                f"{exc} Enter the OAuth app's client ID and secret again.", profile.issuer
            ) from exc
        return auth_config, client_id

    async def _auto_client(
        self, target: ConnectTarget, profile: OAuthProfile
    ) -> tuple[OAuthProfile, ResolvedOAuthApp]:
        source = auto_credential_source(profile)
        if source == "platform":
            app = platform_app_for(profile)
            if app is None:
                raise RuntimeError("auto_credential_source chose a platform app that is gone")
            # Never another workspace's app, and the app's endpoints, not
            # discovery's or a spec's, are where its client secret goes.
            return profile.served_by(app), ResolvedOAuthApp(
                client_id=app.client_id,
                config={"credential_mode": "managed", "platform_oauth_issuer": app.issuer},
            )
        if source == "dynamic":
            try:
                client = await MCPOAuthClientService().register_client(
                    profile.registration_endpoint, callback_uri()
                )
            except (httpx.HTTPError, MCPOAuthDiscoveryError, KeyError, ValueError) as exc:
                logger.info("DCR failed for %s: %s", profile.issuer, exc, exc_info=True)
                count(
                    "oauth_connect",
                    provider=_provider_label(profile.issuer),
                    outcome="failed:dcr_failed",
                )
                raise _oauth_app_required(
                    f"Dynamic client registration with {profile.issuer} failed "
                    f"({exc}). Connect with an OAuth app you registered with this provider.",
                    profile.issuer,
                ) from exc
            return profile, ResolvedOAuthApp(
                client_id=client.client_id,
                config={"client_id": client.client_id, "credential_mode": "dynamic"},
                credentials=(
                    {"client_secret": client.client_secret} if client.client_secret else {}
                ),
            )
        count(
            "oauth_connect",
            provider=_provider_label(profile.issuer),
            outcome="failed:oauth_app_required",
        )
        raise _oauth_app_required(target.oauth_app_required_detail(profile), profile.issuer)


def _with_query(url: str, **params: str) -> str:
    return f"{url}?{urllib.parse.urlencode(params)}"


async def receive(
    *,
    state: str | None,
    code: str | None,
    error: str | None,
    error_description: str | None,
) -> str:
    """Take the provider's redirect back; returns where the browser goes.

    The state token proves the flow was started by authorize, and says which
    connection it is for. It does not prove who followed the provider URL, so
    the code is parked for the person who started the flow to finish in their
    own session, never redeemed here.
    """
    flow = await oauth_state.pop(state) if state else None
    if flow is None:
        count(
            "oauth_connect",
            provider="unknown",
            outcome=f"failed:{_oauth_error(error) if error else 'invalid_state'}",
        )
        if error:
            # Without a usable state neither the page nor the workspace is
            # known: the frontend root opens the user's own workspace.
            return _with_query(
                f"{frontend_base()}/", oauth="error", reason=error_description or error
            )
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")

    if error or not code:
        workspace_slug = await _workspace_slug(flow)
        if workspace_slug is None:
            return _workspace_gone(flow)
        count(
            "oauth_connect",
            provider="unknown",
            outcome=f"failed:{_oauth_error(error) if error else 'missing_code'}",
        )
        return _with_query(
            landing_url(flow, workspace_slug),
            oauth="error",
            reason=error_description or error or "missing_code",
        )

    token = secrets.token_urlsafe(32)
    await oauth_state.store_returned(token, oauth_state.ReturnedFlow(flow=flow, code=code))
    return finish_page_url(flow.return_to, token)


async def finish(
    session: AsyncSession, *, token: str, user_id: str, reachable_workspaces: list[str]
) -> str:
    """Redeem a returned flow's code for the person who started it; returns where they go.

    The caller must also still reach the flow's workspace.
    """
    returned = await oauth_state.pop_returned(token)
    if returned is None:
        count("oauth_connect", provider="unknown", outcome="failed:invalid_state")
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth sign-in")
    flow, code = returned.flow, returned.code
    if flow.user_id != user_id or flow.workspace_id not in reachable_workspaces:
        logger.warning(
            "OAuth finish refused: %s %s in workspace %s was started by %s, finished by %s",
            flow.target_kind,
            flow.connection_id,
            flow.workspace_id,
            flow.user_id,
            user_id,
        )
        count("oauth_connect", provider="unknown", outcome="failed:other_user")
        raise HTTPException(status_code=403, detail="This sign-in was started by someone else")

    workspace_slug = await _workspace_slug(flow)
    if workspace_slug is None:
        return _workspace_gone(flow)
    landing = landing_url(flow, workspace_slug)

    user_context = UserContext(
        user_id=flow.user_id, workspace_id=flow.workspace_id, workspace_slug=workspace_slug
    )
    bind_workspace_scope(user_context.workspace_id)
    auth_service = MCPAuthService(
        MCPAuthConfigRepository(session, user_context),
        get_real_secret_manager(session=session, user_context=user_context),
    )
    auth_config = await auth_service.get(UUID(flow.auth_config_id))
    if auth_config is None:
        count("oauth_connect", provider="unknown", outcome="failed:connection_gone")
        raise HTTPException(status_code=400, detail="OAuth connection no longer exists")
    provider = _provider_label(_auth_config_issuer(auth_config.config))
    try:
        await auth_service.complete_authorization(
            auth_config, code=code, redirect_uri=callback_uri(), code_verifier=flow.code_verifier
        )
    except OAuthCodeExchangeError as exc:
        count("oauth_connect", provider=provider, outcome=f"failed:{exc.reason}")
        return _with_query(landing, oauth="error", reason=exc.reason)
    if flow.scopes is not None:
        await auth_service.update(
            auth_config.id,
            config={**auth_config.config, "scopes": flow.scopes},
            allow_managed_credentials=True,
        )

    await attach_credential(flow, session, user_context, auth_config.id)
    await session.commit()
    logger.info(
        "OAuth connect complete: %s=%s auth_config=%s",
        flow.target_kind,
        flow.connection_id,
        auth_config.id,
    )
    after_connect(flow, user_context)
    count("oauth_connect", provider=provider, outcome="succeeded")
    return _with_query(landing, oauth="success")


async def _workspace_slug(flow: oauth_state.OAuthState) -> str | None:
    try:
        return await workspace_slug_for(flow.workspace_id)
    except LookupError:
        # Deleted while the user was at the provider: no workspace page to return to.
        logger.warning(
            "OAuth flow for %s %s: workspace %s is gone",
            flow.target_kind,
            flow.connection_id,
            flow.workspace_id,
            exc_info=True,
        )
        return None


def _workspace_gone(flow: oauth_state.OAuthState) -> str:
    count("oauth_connect", provider="unknown", outcome="failed:workspace_gone")
    return _with_query(f"{frontend_base(flow.return_to)}/", oauth="error", reason="workspace_gone")
