"""FastAPI dependencies for authentication and workspace selection.

Authentication and workspace selection are separate steps. Authentication
answers who is calling and yields a :class:`UserPrincipal`, which has no
workspace. The workspace comes from the request itself, never from a header
and never from a default:

- ``/v1/workspaces/{workspace}/...`` names it by slug in the path;
- an id-addressed route (A2A, the MCP instance proxy) binds the workspace of
  the entity it addresses through a :func:`binds_workspace` dependency.

Provides:
- authenticate_principal: who is calling (401 if nobody)
- get_principal: the caller with the workspaces they can reach resolved
- get_user_context: the caller acting in the workspace the request selected
- get_optional_principal: like get_principal, but None when no token is sent
"""

import hashlib
import logging
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from ..observability.metrics import AUTHZ_DURATION
from .authorization import AuthorizationService
from .context import (
    UserContext,
    UserPrincipal,
    WorkspaceBoundCredentialError,
    WorkspaceUnreachableError,
)
from .context_manager import ContextManager
from .interfaces import AuthResult
from .providers.factory import AuthProviderFactory

if TYPE_CHECKING:
    from agentarea_common.workspaces.models import Workspace

logger = logging.getLogger(__name__)

_API_KEY_PREFIX = "aat_"
WORKSPACE_PATH_PARAM = "workspace"
WORKSPACE_BINDER_ATTR = "__binds_workspace__"
_WORKSPACE_BINDING_STATE = "agentarea_workspace_binding"
_PRINCIPAL_STATE = "agentarea_principal"


class WorkspaceNotSelectedError(RuntimeError):
    """A route asked for a workspace context but its request selects no workspace.

    A programming error, not a client one: the route belongs under
    ``/v1/workspaces/{workspace}`` or needs a :func:`binds_workspace`
    dependency. The app refuses to start with such a route (see
    ``agentarea_api.api.route_contract``); this is the backstop.
    """


@dataclass(frozen=True)
class _WorkspaceBinding:
    workspace_id: str
    workspace_slug: str


def binds_workspace[F: Callable[..., Any]](dependency: F) -> F:
    """Mark a dependency that selects the request's workspace from the entity it addresses.

    The dependency must authorize the caller against that workspace and then
    call :func:`bind_request_workspace`.
    """
    setattr(dependency, WORKSPACE_BINDER_ATTR, True)
    return dependency


def bind_request_workspace(request: Request, workspace_id: str, workspace_slug: str) -> None:
    """Select the workspace ``get_user_context`` resolves for this request."""
    setattr(
        request.state,
        _WORKSPACE_BINDING_STATE,
        _WorkspaceBinding(workspace_id=workspace_id, workspace_slug=workspace_slug),
    )


def _www_authenticate_bearer() -> str:
    """Return WWW-Authenticate header value with RFC 9728 resource_metadata.

    MCP clients (Cursor, Claude Desktop) use the resource_metadata URL to
    discover OAuth authorization server metadata and start the OAuth flow.
    """
    from agentarea_common.config import get_settings

    api_base = get_settings().app.API_BASE_URL.rstrip("/")
    return f'Bearer resource_metadata="{api_base}/.well-known/oauth-protected-resource"'


async def _member_workspace_ids(user_id: str) -> list[str]:
    """Workspaces the membership graph says ``user_id`` has joined.

    A graph outage must not lock a user out of the workspaces they own, which
    are resolved from rows, so it narrows the list to those instead of failing
    the request. Graph grants stay the membership source of truth: there is no
    fallback to the database.
    """
    from agentarea_common.workspaces.memberships import (
        get_workspace_membership_graph,
        list_workspace_ids_for_member,
    )

    graph = get_workspace_membership_graph()
    if graph is None:
        return []
    try:
        return await list_workspace_ids_for_member(graph, user_id)
    except Exception as exc:
        logger.warning(
            "Could not resolve workspace memberships for user %s: %s",
            user_id,
            exc,
            exc_info=True,
        )
        return []


async def _owned_and_named_workspaces(
    user_id: str, *, slug: str | None = None, workspace_id: str | None = None
) -> "tuple[list[Workspace], Workspace | None]":
    """The workspaces ``user_id`` owns and the one named by slug or id, in one query.

    Database errors propagate: a failed lookup must not read as "no such
    workspace", which would answer a healthy member with 403.
    """
    from agentarea_common.config.database import get_database
    from agentarea_common.workspaces.repository import WorkspaceRepository

    async with get_database().async_session_factory() as session:
        rows = await WorkspaceRepository(session).list_owned_or_named(
            user_id, slug=slug, workspace_id=workspace_id
        )
    owned = [workspace for workspace in rows if workspace.owner_user_id == user_id]
    named = next(
        (
            w
            for w in rows
            if (slug is not None and w.slug == slug)
            or (workspace_id is not None and w.id == workspace_id)
        ),
        None,
    )
    return owned, named


async def _resolve_access(
    principal: UserPrincipal, *, slug: str | None = None, workspace_id: str | None = None
) -> "Workspace | None":
    """Fill the workspaces ``principal`` can reach and administer.

    Combines what the ``AuthorizationService`` grants, graph memberships, and
    ownership, which is authoritative even for a workspace that predates graph
    provisioning and is what confers administrative authority. An API key is
    narrowed to the workspace it was issued for. Returns the workspace ``slug``
    or ``workspace_id`` names, looked up in the same query as ownership,
    whether or not it is reachable -- the caller decides.
    """
    with AUTHZ_DURATION.labels(operation="resolve_access").time():
        return await _resolve_access_unobserved(principal, slug=slug, workspace_id=workspace_id)


async def _resolve_access_unobserved(
    principal: UserPrincipal, *, slug: str | None, workspace_id: str | None
) -> "Workspace | None":
    from agentarea_common.di.container import resolve

    authz = resolve(AuthorizationService)
    accessible = list(await authz.get_accessible_workspaces(principal))
    for member_of in await _member_workspace_ids(principal.user_id):
        if member_of not in accessible:
            accessible.append(member_of)

    owned, named = await _owned_and_named_workspaces(
        principal.user_id, slug=slug, workspace_id=workspace_id
    )
    administered = [workspace.id for workspace in owned]
    for owned_id in administered:
        if owned_id not in accessible:
            accessible.append(owned_id)

    if principal.bound_workspace_id is not None:
        accessible = [w for w in accessible if w == principal.bound_workspace_id]
        administered = [w for w in administered if w == principal.bound_workspace_id]

    principal.accessible_workspaces = accessible
    principal.admin_workspaces = administered
    return named


def _forbidden_workspace(principal: UserPrincipal, reference: str) -> HTTPException:
    logger.warning(
        "Rejected workspace selection: user=%s requested=%s accessible=%s",
        principal.user_id,
        reference,
        principal.accessible_workspaces,
    )
    # One answer for unknown and foreign workspaces: no existence oracle.
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="User is not a member of the requested workspace",
    )


async def enter_workspace(principal: UserPrincipal, reference: str) -> UserContext:
    """Act as ``principal`` in the workspace ``reference`` names by slug or id.

    For the MCP surfaces, whose URLs and tool arguments accept either form. A
    UUID-shaped reference is an id and is looked up as nothing else, so a slug
    minted to look like someone's workspace id cannot capture it. Raises
    :class:`WorkspaceUnreachableError` alike for an unknown workspace and a
    foreign one.
    """
    from agentarea_common.workspaces.lookup import load_workspace
    from agentarea_common.workspaces.slug import is_uuid_shaped

    if principal.accessible_workspaces is None:
        await _resolve_access(principal)
    if is_uuid_shaped(reference):
        workspace = await load_workspace(workspace_id=reference)
    else:
        workspace = await load_workspace(slug=reference)
    if workspace is None:
        raise WorkspaceUnreachableError(f"No accessible workspace '{reference}'")
    return principal.enter(workspace.id, workspace.slug)


# Security schemes
# Required authentication - raises 401 with RFC 9728 resource_metadata if no token
# NOTE: We use auto_error=False and raise manually so the WWW-Authenticate header
# includes the resource_metadata URL that MCP clients need for OAuth discovery.
security_required = HTTPBearer(auto_error=False)

# Optional authentication - returns None if no token (doesn't raise error)
security_optional = HTTPBearer(auto_error=False)


async def _owns_workspace(session: AsyncSession, user_id: str, workspace_id: str) -> bool:
    """Whether ``workspace_id`` is ``user_id``'s personal workspace or one they own."""
    from agentarea_common.workspaces.repository import WorkspaceRepository

    if workspace_id == user_id:
        return True
    workspace = await WorkspaceRepository(session).get(workspace_id)
    return workspace is not None and workspace.owner_user_id == user_id


async def _has_graph_membership(user_id: str, workspace_id: str) -> bool:
    """Whether the membership graph grants ``user_id`` ``workspace_id``. A failure denies.

    A network call: callers make it with no database session open, so a pooled
    connection never waits on the graph.
    """
    from agentarea_common.workspaces import memberships

    try:
        return await memberships.check_workspace_membership(
            memberships.get_workspace_membership_graph(),
            workspace_id=workspace_id,
            user_id=user_id,
        )
    except Exception:
        logger.exception(
            "Could not check membership of user %s in workspace %s", user_id, workspace_id
        )
        return False


API_KEY_USE_WRITE_INTERVAL = timedelta(seconds=60)
# Uses this process counted but has not written yet, by key id. They ride along
# with the key's next write; a process that exits first loses at most one
# interval's worth.
_unwritten_api_key_uses: defaultdict[Any, int] = defaultdict(int)


async def _record_api_key_use(key_id: Any, last_written: datetime | None) -> None:
    """Count one use of an API key, writing at most once per interval.

    Writing on every request put an UPDATE and a COMMIT in front of each
    API-key call. A failed write is logged and its uses kept for the next one:
    the stamp is bookkeeping, and a request must not fail over it.
    """
    from agentarea_mcp.domain.auth_models import APIKey
    from sqlalchemy import update

    from agentarea_common.config import get_database

    _unwritten_api_key_uses[key_id] += 1
    now = datetime.utcnow()
    if last_written is not None and now - last_written < API_KEY_USE_WRITE_INTERVAL:
        return
    uses = _unwritten_api_key_uses.pop(key_id)
    try:
        async with get_database().async_session_factory() as session:
            await session.execute(
                update(APIKey)
                .where(APIKey.id == key_id)
                .values(access_count=APIKey.access_count + uses, last_accessed_at=now)
            )
            await session.commit()
    except Exception:
        _unwritten_api_key_uses[key_id] += uses
        logger.warning("Could not record use of API key %s", key_id, exc_info=True)


async def _validate_api_key(token: str, request: Request) -> UserPrincipal | None:
    """Validate an API key and return its principal, or None if invalid.

    A key carries no authority of its own: it is only as good as its owner's
    current membership of the key's workspace.
    """
    from agentarea_mcp.domain.auth_models import APIKey
    from sqlalchemy import select

    from agentarea_common.config import get_database

    token_hash = hashlib.sha256(token.encode()).hexdigest()

    async with get_database().async_session_factory() as session:
        result = await session.execute(select(APIKey).where(APIKey.token_hash == token_hash))
        record = result.scalar_one_or_none()

        if record is None or not record.is_active:
            return None
        if record.expires_at and datetime.utcnow() >= record.expires_at:
            return None
        key_id = record.id
        last_written = record.last_accessed_at
        user_id = str(record.created_by)
        workspace_id = str(record.workspace_id)
        owned = await _owns_workspace(session, user_id, workspace_id)

    if not owned and not await _has_graph_membership(user_id, workspace_id):
        logger.warning(
            "API key %s refused: its owner %s is not a member of workspace %s",
            key_id,
            user_id,
            workspace_id,
        )
        return None

    await _record_api_key_use(key_id, last_written)

    # The key acts for its creator, and only in the workspace it was issued
    # for: _resolve_access narrows the principal's reach to that one.
    return UserPrincipal(user_id=user_id, bound_workspace_id=workspace_id)


def get_auth_provider():
    """Get the configured authentication provider.

    Returns configured Kratos auth provider from application settings.
    """
    from agentarea_common.config.auth import get_auth_settings

    settings = get_auth_settings()

    return AuthProviderFactory.create_provider(
        "kratos",
        config={
            "jwks_b64": settings.KRATOS_JWKS_B64,
            "issuer": settings.KRATOS_ISSUER,
            "audience": settings.KRATOS_AUDIENCE,
        },
    )


# ---------------------------------------------------------------------------
# Hydra OAuth token validation (for MCP clients: Cursor, Claude Desktop)
# ---------------------------------------------------------------------------
_hydra_jwks_client = None


def _get_hydra_jwks():
    """Get or create Hydra JWKS client (cached)."""
    global _hydra_jwks_client
    if _hydra_jwks_client is not None:
        return _hydra_jwks_client

    import jwt as pyjwt

    from agentarea_common.config import get_settings

    settings = get_settings()
    jwks_url = f"{settings.mcp.HYDRA_PUBLIC_URL.rstrip('/')}/.well-known/jwks.json"
    _hydra_jwks_client = pyjwt.PyJWKClient(jwks_url, cache_keys=True)
    logger.info(f"Hydra JWKS client initialized: {jwks_url}")
    return _hydra_jwks_client


async def _try_hydra_token(token: str, request: Request) -> UserPrincipal | None:
    """Try to validate a JWT as a Hydra-issued OAuth token.

    Returns the principal if valid, None otherwise. Used as a fallback when
    Kratos validation fails — MCP clients (Cursor, Claude Desktop) authenticate
    via Hydra OAuth 2.1 and their tokens are signed with Hydra's keys.
    """
    import jwt as pyjwt

    from agentarea_common.config import get_settings

    try:
        jwks_client = _get_hydra_jwks()
        signing_key = jwks_client.get_signing_key_from_jwt(token)

        # Audience verification is mandatory. It used to be toggled by whether
        # HYDRA_AUDIENCE happened to be set, and it was set in no chart, compose
        # file or env template — so `aud` was never checked anywhere, and any
        # token Hydra had ever signed was accepted on every protected route.
        #
        # An unset HYDRA_AUDIENCE now DISABLES this auth path rather than
        # weakening it: deployments that do not run Hydra (the prod compose does
        # not) keep working, and deployments that do must say which audience they
        # accept.
        hydra_audience = get_settings().mcp.HYDRA_AUDIENCE
        if not hydra_audience:
            logger.warning(
                "Hydra bearer token presented but HYDRA_AUDIENCE is not configured; "
                "refusing the token. Set HYDRA_AUDIENCE to this API's resource "
                "identifier to enable MCP OAuth."
            )
            return None

        payload = pyjwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=hydra_audience,
            options={"verify_aud": True},
        )

        subject = payload.get("sub", "")
        if not subject:
            return None
        # Hydra names the client itself as the subject of a client_credentials
        # token: no user logged in, so there is no principal to act as.
        if subject == payload.get("client_id"):
            logger.warning("Hydra token refused: subject is its own client %s", subject)
            return None

        # OAuth identifies the principal, never its active tenant: any
        # workspace claim in the token is ignored.
        return UserPrincipal(user_id=subject)

    except Exception as e:
        logger.debug(f"Hydra token verification failed: {e}")
        return None


async def _authenticate_token(token: str, request: Request) -> UserPrincipal:
    """Resolve a bearer token to its principal, once per request.

    Accepts an AgentArea API key (``aat_``), a Kratos JWT, and a Hydra OAuth
    token. Raises 401 when no provider accepts the token, 500 when verifying it
    fails outright. Optional and required authentication are separate
    dependencies, so a route using both (A2A: the binder, then the workspace
    context) would otherwise verify the token twice and count an API key use
    twice; the principal is kept on the request instead.
    """
    cached = getattr(request.state, _PRINCIPAL_STATE, None)
    if cached is not None and cached[0] == token:
        return cached[1]
    principal = await _verify_token(token, request)
    setattr(request.state, _PRINCIPAL_STATE, (token, principal))
    return principal


async def _verify_token(token: str, request: Request) -> UserPrincipal:
    if token.startswith(_API_KEY_PREFIX):
        principal = await _validate_api_key(token, request)
        if principal is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired API key",
                headers={"WWW-Authenticate": _www_authenticate_bearer()},
            )
        return principal

    try:
        auth_result: AuthResult = await get_auth_provider().verify_token(token)
    except Exception as e:
        # Kratos threw — try Hydra as last resort
        hydra_principal = await _try_hydra_token(token, request)
        if hydra_principal is not None:
            return hydra_principal
        logger.error(f"Unexpected error during authentication: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error during authentication",
        ) from e

    if auth_result.is_authenticated and auth_result.token:
        return UserPrincipal(user_id=auth_result.token.user_id, email=auth_result.token.email)

    # Kratos rejected — try a Hydra OAuth token before failing
    hydra_principal = await _try_hydra_token(token, request)
    if hydra_principal is not None:
        return hydra_principal

    logger.warning(f"Authentication failed: {auth_result.error}")
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=auth_result.error or "Invalid authentication token",
        headers={"WWW-Authenticate": _www_authenticate_bearer()},
    )


async def authenticate_principal(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security_required),
) -> UserPrincipal:
    """Who is calling (REQUIRED authentication). Raises 401 if nobody.

    Selects no workspace and resolves no access; see :func:`get_principal` and
    :func:`get_user_context`.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication credentials",
            headers={"WWW-Authenticate": _www_authenticate_bearer()},
        )
    return await _authenticate_token(credentials.credentials, request)


async def get_principal(
    principal: UserPrincipal = Depends(authenticate_principal),
) -> UserPrincipal:
    """The authenticated caller with the workspaces they can reach resolved.

    For routes that act on no single workspace: listing and creating
    workspaces, accepting an invitation, and the binders of id-addressed routes.
    """
    await _resolve_access(principal)
    return principal


def ensure_not_workspace_bound(principal: UserPrincipal) -> None:
    """Refuse a credential bound to one workspace on a route that names none.

    An API key acts only in the workspace it was issued for. A route without a
    workspace in its path cannot confine it, so actions there that reach
    beyond that workspace (creating one, joining one) need a user session.
    """
    if principal.bound_workspace_id is not None:
        raise WorkspaceBoundCredentialError(
            "An API key acts only in the workspace it was issued for; "
            "sign in as a user to create or join workspaces"
        )


async def get_unbound_principal(
    principal: UserPrincipal = Depends(get_principal),
) -> UserPrincipal:
    """The caller, provided its credential is not confined to one workspace."""
    ensure_not_workspace_bound(principal)
    return principal


async def get_user_context(
    request: Request,
    principal: UserPrincipal = Depends(authenticate_principal),
) -> UserContext:
    """The caller acting in the workspace this request selects.

    The workspace is the ``{workspace}`` slug in the path (a UUID-shaped one
    is a workspace id and resolves by id only), or the one a
    :func:`binds_workspace` dependency bound from the entity the route
    addresses. An unknown slug and a workspace the caller cannot reach are
    refused with the same 403. A request that selects neither is a routing bug
    and raises :class:`WorkspaceNotSelectedError`; there is no default.
    """
    from agentarea_common.workspaces.slug import is_uuid_shaped, is_valid_workspace_slug

    reference = request.path_params.get(WORKSPACE_PATH_PARAM)
    if reference is not None:
        # Checked here, before any lookup: the route's Path declaration only
        # reports its error after every dependency has run.
        if not is_valid_workspace_slug(reference):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Malformed workspace reference in the path",
            )
        if is_uuid_shaped(reference):
            workspace = await _resolve_access(principal, workspace_id=reference)
        else:
            workspace = await _resolve_access(principal, slug=reference)
        if workspace is None:
            raise _forbidden_workspace(principal, reference)
        workspace_id, workspace_slug = workspace.id, workspace.slug
    else:
        binding = getattr(request.state, _WORKSPACE_BINDING_STATE, None)
        if binding is None:
            raise WorkspaceNotSelectedError(
                f"{request.method} {request.url.path} needs a workspace context but "
                "names no workspace and binds none"
            )
        if principal.accessible_workspaces is None:
            await _resolve_access(principal)
        workspace_id, workspace_slug = binding.workspace_id, binding.workspace_slug

    try:
        user_context = principal.enter(workspace_id, workspace_slug)
    except WorkspaceUnreachableError:
        raise _forbidden_workspace(principal, workspace_slug) from None

    ContextManager.set_context(user_context)
    logger.debug(
        f"Authenticated user: {user_context.user_id} in workspace: {user_context.workspace_id}"
    )
    return user_context


async def resolve_principal_from_token(token: str | None, request: Request) -> UserPrincipal | None:
    """Resolve a principal from a bearer token, or None if absent/invalid.

    This is the single authentication resolution shared by every optional-auth
    edge -- REST optional auth, the A2A protocol, the MCP mounts -- so an
    AgentArea API key (``aat_``), a Kratos JWT, and a Hydra OAuth token are all
    accepted the same way at every entry point. It never raises for an auth
    failure; it returns None so the caller decides the posture (401, anonymous
    subject, ...). The returned principal has its reachable workspaces resolved.
    """
    if not token:
        return None
    try:
        principal = await _authenticate_token(token, request)
    except HTTPException as exc:
        logger.debug("Token authentication failed: %s", exc.detail)
        return None
    await _resolve_access(principal)
    return principal


async def get_optional_principal(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security_optional),
) -> UserPrincipal | None:
    """Optionally authenticate the caller if a token is provided (OPTIONAL authentication).

    Returns the principal if a valid token is provided, None otherwise. Does
    NOT raise 401 if no token is provided.
    """
    if not credentials:
        logger.debug("No authentication credentials provided (optional auth)")
        return None

    return await resolve_principal_from_token(credentials.credentials, request)


# Type aliases for easier use in endpoint dependencies
UserContextDep = Annotated[UserContext, Depends(get_user_context)]
PrincipalDep = Annotated[UserPrincipal, Depends(get_principal)]
UnboundPrincipalDep = Annotated[UserPrincipal, Depends(get_unbound_principal)]
OptionalPrincipalDep = Annotated[UserPrincipal | None, Depends(get_optional_principal)]
