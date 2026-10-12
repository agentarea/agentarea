"""What an OAuth flow connects: where its profile comes from, and what the token is for.

Two kinds start a flow — a remote MCP instance, and a trusted catalog API
template that becomes an OpenAPI connection — and a catalog MCP spec can be
asked about before any instance exists. Everything else in the flow is shared.
"""

import asyncio
import logging
from typing import Any, Protocol
from urllib.parse import urlparse
from uuid import UUID

from agentarea_common.auth.context import UserContext
from agentarea_common.auth.permission import require_permission
from agentarea_common.base.repository_factory import RepositoryFactory
from agentarea_common.config.database import get_database
from agentarea_common.events.broker import EventBroker
from agentarea_common.utils.url_safety import OutboundPolicy
from agentarea_mcp.application.auth_resolver import (
    build_auth_config_access_checker,
    build_owned_auth_releaser,
)
from agentarea_mcp.application.oauth_client_service import (
    MCPOAuthClientService,
    MCPOAuthDiscoveryError,
    checked_authorize_params,
    discovered_profile,
    oauth_app_required_detail,
    oauth_authorize_params,
)
from agentarea_mcp.application.oauth_profile import OAuthProfile
from agentarea_mcp.domain.transport import MCPTransport
from agentarea_mcp.infrastructure.repository import (
    MCPServerInstanceRepository,
    MCPServerRepository,
)
from agentarea_mcp.transport_spec import instance_transport_spec, server_transport_spec
from agentarea_openapi.application.service import OpenAPIConnectionService
from agentarea_openapi.application.url_validator import validate_url
from agentarea_openapi.infrastructure.repository import OpenAPIConnectionRepository
from agentarea_openapi.schemas.dto import OpenAPIConnectionCreate
from agentarea_registry.infrastructure.repository import RegistryItemRepository, RegistryRepository
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from agentarea_api.api.deps.services import get_real_secret_manager
from agentarea_api.oauth_connect.pages import (
    mcp_instance_landing_url,
    openapi_connection_landing_url,
)
from agentarea_api.oauth_connect.state import OAuthState, TargetKind

logger = logging.getLogger(__name__)
_background_tasks: set[asyncio.Task[None]] = set()


class NotAuthorizableError(Exception):
    """This target cannot be authorized with OAuth; ``detail`` says why.

    Preflight renders it as ``unsupported``; authorize answers ``status_code``.
    """

    def __init__(self, detail: str, status_code: int) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


class PreflightTarget(Protocol):
    """Something a person may be asked to sign in to."""

    connected: bool

    async def profile(self) -> OAuthProfile:
        """The authorization server this target signs in with.

        Raises:
            NotAuthorizableError: when it has none.
        """
        ...

    def oauth_app_required_detail(self, profile: OAuthProfile) -> str: ...


class ConnectTarget(PreflightTarget, Protocol):
    """Something a person signs in to now."""

    async def ensure_may_authorize(self) -> None: ...

    async def create_connection(self) -> tuple[TargetKind, UUID]:
        """The connection the callback attaches the credential to, made now if it is new."""
        ...

    def auth_config_name(self, connection_id: UUID) -> str: ...


# ---------------------------------------------------------------------------
# Remote MCP servers
# ---------------------------------------------------------------------------


class _NoopEventBroker(EventBroker):
    async def publish(self, event: Any) -> None:
        return None


def instance_remote_url(instance: Any, server_spec: Any) -> str | None:
    """The remote MCP URL a URL-type instance connects to, else None."""
    if server_spec is None or instance.transport != MCPTransport.URL:
        return None
    return instance_transport_spec(server_spec, instance).get("endpoint_url") or None


def _spec_remote_url(server_spec: Any) -> str | None:
    spec = server_transport_spec(server_spec)
    if spec.get("type") != MCPTransport.URL:
        return None
    return spec.get("endpoint_url") or None


async def _discovered(mcp_url: str | None, server_spec: Any) -> OAuthProfile:
    if not mcp_url:
        raise NotAuthorizableError(
            "No remote URL configured. OAuth connect requires a URL-type MCP connection.",
            status_code=400,
        )
    try:
        authorize_params = oauth_authorize_params(server_spec.json_spec if server_spec else None)
    except ValueError as exc:
        raise NotAuthorizableError(
            f"The MCP server spec's OAuth settings are invalid: {exc}", status_code=502
        ) from exc
    try:
        metadata = await MCPOAuthClientService().discover_auth_server(mcp_url)
    except MCPOAuthDiscoveryError as exc:
        raise NotAuthorizableError(str(exc), status_code=502) from exc
    return discovered_profile(metadata, mcp_url, authorize_params)


class MCPInstanceTarget:
    """An MCP instance: the callback attaches the credential to it."""

    def __init__(self, instance: Any, server_spec: Any, user_context: UserContext) -> None:
        self.instance = instance
        self.server_spec = server_spec
        self.user_context = user_context
        self.connected = instance.auth_config_id is not None

    @classmethod
    async def load(
        cls, instance_id: UUID, user_context: UserContext, session: AsyncSession
    ) -> "MCPInstanceTarget":
        instance = await MCPServerInstanceRepository(session, user_context).get_by_id(instance_id)
        if instance is None:
            raise HTTPException(status_code=404, detail="MCP instance not found")
        server_spec = None
        if instance.server_spec_id:
            server_spec = await MCPServerRepository(session, user_context).get_server_by_id(
                instance.server_spec_id
            )
        return cls(instance, server_spec, user_context)

    async def profile(self) -> OAuthProfile:
        return await _discovered(
            instance_remote_url(self.instance, self.server_spec), self.server_spec
        )

    def oauth_app_required_detail(self, profile: OAuthProfile) -> str:
        return oauth_app_required_detail(profile.issuer or profile.authorization_endpoint)

    async def ensure_may_authorize(self) -> None:
        # Completing the flow attaches the caller's provider account to the
        # instance, so starting it is an edit.
        await require_permission(
            "edit", "mcp_instance", str(self.instance.id), self.user_context.user_id
        )

    async def create_connection(self) -> tuple[TargetKind, UUID]:
        return "mcp_instance", self.instance.id

    def auth_config_name(self, connection_id: UUID) -> str:
        return f"mcp-oauth-{str(connection_id)[:8]}"


class MCPSpecTarget:
    """A catalog MCP spec, asked about before any instance is created from it."""

    connected = False

    def __init__(self, server_spec: Any) -> None:
        self.server_spec = server_spec

    @classmethod
    async def load(
        cls, server_id: UUID, user_context: UserContext, session: AsyncSession
    ) -> "MCPSpecTarget":
        server_spec = await MCPServerRepository(session, user_context).get_server_by_id(
            str(server_id)
        )
        if server_spec is None:
            raise HTTPException(status_code=404, detail="MCP server spec not found")
        return cls(server_spec)

    async def profile(self) -> OAuthProfile:
        return await _discovered(_spec_remote_url(self.server_spec), self.server_spec)

    def oauth_app_required_detail(self, profile: OAuthProfile) -> str:
        return oauth_app_required_detail(profile.issuer or profile.authorization_endpoint)


# ---------------------------------------------------------------------------
# Trusted catalog API templates
# ---------------------------------------------------------------------------


def _origin(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise HTTPException(status_code=400, detail="Catalog OAuth URLs must use HTTPS")
    return f"{parsed.scheme}://{parsed.netloc}"


def catalog_oauth_profile(spec: dict[str, Any]) -> dict[str, Any]:
    """A catalog template's ``oauth`` block, checked before anything trusts it."""
    oauth = spec.get("oauth")
    if not isinstance(oauth, dict):
        raise HTTPException(status_code=400, detail="Connection does not support OAuth")

    required = ("provider_key", "authorization_url", "token_url")
    missing = [field for field in required if not oauth.get(field)]
    if missing:
        raise HTTPException(
            status_code=500,
            detail=f"Catalog OAuth template is missing: {', '.join(missing)}",
        )

    for url_field in ("authorization_url", "token_url"):
        url = str(oauth[url_field])
        _origin(url)
        try:
            validate_url(url, policy=OutboundPolicy())
        except ValueError as exc:
            raise HTTPException(status_code=500, detail="Catalog OAuth URL is not allowed") from exc
    scheme = str(oauth.get("authorization_scheme") or "Bearer")
    if scheme not in {"Bearer", "OAuth"}:
        raise HTTPException(status_code=500, detail="Unsupported authorization scheme")
    method = str(oauth.get("client_auth_method") or "client_secret_post")
    if method not in {"client_secret_post", "client_secret_basic"}:
        raise HTTPException(status_code=500, detail="Unsupported OAuth client auth method")
    scopes = oauth.get("scopes") or []
    if not isinstance(scopes, list) or not all(isinstance(scope, str) for scope in scopes):
        raise HTTPException(status_code=500, detail="Invalid OAuth scopes")
    authorize_params = oauth.get("authorize_params") or {}
    try:
        if not isinstance(authorize_params, dict) or not all(
            isinstance(value, str) for value in authorize_params.values()
        ):
            raise ValueError("authorize_params must be an object of strings")
        authorize_params = checked_authorize_params(authorize_params)
    except ValueError as exc:
        raise HTTPException(status_code=500, detail="Invalid OAuth authorize params") from exc
    return {
        **oauth,
        "authorization_scheme": scheme,
        "client_auth_method": method,
        "scopes": scopes,
        "authorize_params": authorize_params,
    }


class CatalogItemTarget:
    """A trusted catalog API template; each sign-in materializes a new OpenAPI connection."""

    connected = False

    def __init__(
        self,
        item_id: UUID,
        item: Any,
        spec: dict[str, Any],
        oauth: dict[str, Any],
        base_url: str,
        allowed_origins: list[str],
        user_context: UserContext,
        session: AsyncSession,
    ) -> None:
        self.item_id = item_id
        self.item = item
        self.spec = spec
        self.oauth = oauth
        self.base_url = base_url
        self.allowed_origins = allowed_origins
        self.user_context = user_context
        self.session = session

    @classmethod
    async def load(
        cls, item_id: UUID, user_context: UserContext, session: AsyncSession
    ) -> "CatalogItemTarget":
        item = await RegistryItemRepository(session, user_context).get_by_id(item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Catalog connection not found")
        registry = await RegistryRepository(session, user_context).get_by_id(item.registry_id)
        spec = item.spec or {}
        if (
            registry is None
            or not registry.is_active
            or registry.registry_type != "mcp_servers"
            or spec.get("connection_type") != "openapi"
        ):
            raise HTTPException(
                status_code=400, detail="Catalog item is not a one-click API connection"
            )
        oauth = catalog_oauth_profile(spec)
        base_url = str(spec.get("base_url") or "")
        base_origin = _origin(base_url)
        allowed_origins = oauth.get("allowed_api_origins") or [base_origin]
        if not isinstance(allowed_origins, list) or base_origin not in allowed_origins:
            raise HTTPException(
                status_code=500, detail="Catalog OAuth API origin is not allowlisted"
            )
        if any(_origin(str(origin)) != origin for origin in allowed_origins):
            raise HTTPException(
                status_code=500, detail="Catalog OAuth origin must be an exact origin"
            )
        return cls(
            item_id,
            item,
            spec,
            oauth,
            base_url,
            [str(origin) for origin in allowed_origins],
            user_context,
            session,
        )

    async def profile(self) -> OAuthProfile:
        return OAuthProfile(
            provider=str(self.oauth["provider_key"]),
            authorization_endpoint=str(self.oauth["authorization_url"]),
            token_endpoint=str(self.oauth["token_url"]),
            resource_origins=tuple(self.allowed_origins),
            scopes=tuple(self.oauth["scopes"]),
            authorize_params=self.oauth["authorize_params"],
            authorization_scheme=self.oauth["authorization_scheme"],
            client_auth_method=self.oauth["client_auth_method"],
        )

    def oauth_app_required_detail(self, profile: OAuthProfile) -> str:
        name = self.item.name
        return (
            f"This AgentArea installation has no OAuth app for {name}. "
            f"Register your own OAuth app with {name} using the redirect URI "
            "below, then enter its client ID and client secret."
        )

    async def ensure_may_authorize(self) -> None:
        # The connection is created for the caller, by the caller.
        return None

    async def create_connection(self) -> tuple[TargetKind, UUID]:
        secret_manager = get_real_secret_manager(
            session=self.session, user_context=self.user_context
        )
        repository_factory = RepositoryFactory(self.session, self.user_context)
        service = OpenAPIConnectionService(
            repository_factory=repository_factory,
            secret_manager=secret_manager,
            auth_config_access_checker=build_auth_config_access_checker(
                repository_factory, secret_manager
            ),
            owned_auth_releaser=build_owned_auth_releaser(repository_factory, secret_manager),
            outbound_policy=OutboundPolicy.from_env(),
        )
        # A catalog item is a reusable connection definition, not a singleton:
        # each sign-in creates an independently governable account.
        connection = await service.create_connection(
            OpenAPIConnectionCreate(
                name=self.item.name,
                description=self.item.description,
                base_url=self.base_url,
                spec_url=self.spec.get("spec_url"),
                spec_content=self.spec.get("spec_content"),
            ),
            registry_item_id=self.item_id,
            allowed_auth_origins=self.allowed_origins,
            status="pending",
        )
        return "openapi_connection", connection.id

    def auth_config_name(self, connection_id: UUID) -> str:
        return f"{self.oauth['provider_key']}-{str(connection_id)[:8]}"


# ---------------------------------------------------------------------------
# The callback's half: attach the credential, and where the browser lands
# ---------------------------------------------------------------------------


def landing_url(state: OAuthState, workspace_slug: str) -> str:
    if state.target_kind == "mcp_instance":
        return mcp_instance_landing_url(state.return_to, workspace_slug, state.connection_id)
    return openapi_connection_landing_url(state.return_to, workspace_slug, state.connection_id)


async def attach_credential(
    state: OAuthState, session: AsyncSession, user_context: UserContext, auth_config_id: UUID
) -> None:
    connection_id = UUID(state.connection_id)
    if state.target_kind == "mcp_instance":
        await MCPServerInstanceRepository(session, user_context).update(
            connection_id, auth_config_id=auth_config_id
        )
        return
    connection = await OpenAPIConnectionRepository(session, user_context).update(
        connection_id, auth_config_id=auth_config_id, status="active"
    )
    if connection is None:
        raise HTTPException(status_code=404, detail="Connection not found")


def after_connect(state: OAuthState, user_context: UserContext) -> None:
    """What runs once the credential is committed; never blocks the redirect."""
    if state.target_kind != "mcp_instance":
        return
    task = asyncio.create_task(discover_after_oauth(user_context, UUID(state.connection_id)))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def discover_after_oauth(user_context: UserContext, instance_id: UUID) -> None:
    """Discover an instance's tools once it is authorized, on a session of its own."""
    from agentarea_mcp.application.service import MCPServerInstanceService

    try:
        async with get_database().session() as session:
            service = MCPServerInstanceService(
                repository_factory=RepositoryFactory(session=session, user_context=user_context),
                event_broker=_NoopEventBroker(),
                secret_manager=get_real_secret_manager(session=session, user_context=user_context),
            )
            success = await service.discover_and_store_tools(instance_id)
        if success:
            logger.info("Post-OAuth tool discovery succeeded for %s", instance_id)
        else:
            logger.warning("Post-OAuth tool discovery returned False for %s", instance_id)
    except Exception:
        logger.exception("Post-OAuth tool discovery failed for %s", instance_id)
