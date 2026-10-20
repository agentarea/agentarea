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
from typing import Literal
from uuid import UUID

import httpx
from agentarea_common.auth.context import UserContext
from agentarea_common.base.tenant_scope import bind_workspace_scope
from agentarea_common.exceptions import AppError
from agentarea_common.workspaces.lookup import workspace_slug_for
from agentarea_mcp.application.auth_service import MCPAuthService, OAuthCodeExchangeError
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
    credential_source: CredentialSource | None = None
    detail: str = ""
    issuer: str | None = None
    authorization_endpoint: str | None = None
    scopes: tuple[str, ...] = ()


@dataclass(frozen=True)
class Authorization:
    authorize_url: str
    connection_id: UUID


def _oauth_app_required(detail: str, issuer: str | None) -> AppError:
    return AppError(detail, status_code=422, code="oauth_app_required", extra={"issuer": issuer})


async def preflight(target: PreflightTarget) -> Preflight:
    """Every outcome is an answer: "no OAuth here" is rendered, not decoded from an error."""
    try:
        profile = await target.profile()
    except NotAuthorizableError as exc:
        return Preflight(status="unsupported", connected=target.connected, detail=exc.detail)
    source = auto_credential_source(profile)
    return Preflight(
        status="ready" if source else "oauth_app_required",
        connected=target.connected,
        credential_source=source,
        detail="" if source else target.oauth_app_required_detail(profile),
        issuer=profile.issuer,
        authorization_endpoint=profile.authorization_endpoint,
        scopes=profile.scopes,
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
    ) -> Authorization:
        await target.ensure_may_authorize()
        try:
            profile = await target.profile()
        except NotAuthorizableError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

        secret_manager = get_real_secret_manager(
            session=self._session, user_context=self._user_context
        )
        if credential_mode == "custom":
            resolved = await resolve_custom_oauth_app(
                custom, catalog=self._secret_catalog, manager=secret_manager
            )
            resolved.config["credential_mode"] = "custom"
        else:
            profile, resolved = await self._auto_client(target, profile)

        kind, connection_id = await target.create_connection()
        auth_service = MCPAuthService(
            MCPAuthConfigRepository(self._session, self._user_context), secret_manager
        )
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
                "scopes": list(profile.scopes),
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
            ),
        )
        authorize_url = MCPOAuthClientService().build_authorize_url(
            profile,
            client_id=resolved.client_id,
            redirect_uri=callback_uri(),
            pkce=pkce,
            state=token,
        )
        return Authorization(authorize_url=authorize_url, connection_id=connection_id)

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
        raise HTTPException(status_code=400, detail="OAuth connection no longer exists")
    try:
        await auth_service.complete_authorization(
            auth_config, code=code, redirect_uri=callback_uri(), code_verifier=flow.code_verifier
        )
    except OAuthCodeExchangeError as exc:
        return _with_query(landing, oauth="error", reason=exc.reason)

    await attach_credential(flow, session, user_context, auth_config.id)
    await session.commit()
    logger.info(
        "OAuth connect complete: %s=%s auth_config=%s",
        flow.target_kind,
        flow.connection_id,
        auth_config.id,
    )
    after_connect(flow, user_context)
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
    return _with_query(f"{frontend_base(flow.return_to)}/", oauth="error", reason="workspace_gone")
