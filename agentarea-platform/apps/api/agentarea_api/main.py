"""Main FastAPI application for AgentArea."""

import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import cast

# Suppress noisy third-party loggers before any imports trigger them
for _noisy_logger in ("LiteLLM", "LiteLLM Proxy", "LiteLLM Router", "httpcore", "httpx"):
    logging.getLogger(_noisy_logger).setLevel(logging.WARNING)

from agentarea_common.auth.route_authz import unrestricted
from agentarea_common.di.container import get_container, register_factory, register_singleton
from agentarea_common.events.broker import EventBroker
from agentarea_common.exceptions.registration import register_error_handlers
from agentarea_common.logging import setup_logging
from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.security import HTTPBearer
from fastapi.staticfiles import StaticFiles

from agentarea_api.api.route_contract import check_route_contract
from agentarea_api.api.v1.mcp_oauth_as import oauth_as_router
from agentarea_api.api.v1.router import (
    WORKSPACE_PREFIX,
    a2a_v1_router,
    mcp_proxy_v1_router,
    principal_v1_router,
    public_v1_router,
    workspace_v1_router,
)

# Configure structured (JSON) logging once at import time. The noisy third-party
# loggers above keep their WARNING level (disable_existing_loggers is False).
setup_logging(enable_structured_logging=True)

logger = logging.getLogger(__name__)
container = get_container()


async def initialize_services():
    """Initialize real services instead of test mocks."""
    try:
        # Discover extensions and wire DI
        from agentarea_common.auth.authorization import AuthorizationService
        from agentarea_common.auth.permission import PermissionService
        from agentarea_common.auth.workspace_authorization import (
            WorkspaceScopedAuthorizationService,
        )
        from agentarea_common.config.app import get_app_settings
        from agentarea_common.extensions import discover_extensions
        from agentarea_common.extensions.registry import ExtensionRegistry
        from agentarea_common.features.service import DeploymentMode, FeatureService

        discover_extensions()

        app_settings = get_app_settings()
        mode = DeploymentMode(app_settings.DEPLOYMENT_MODE)
        register_singleton(FeatureService, FeatureService(mode=mode))

        from agentarea_common.config import get_settings

        settings = get_settings()

        # Shared graph clients (used by the rebac API + PermissionService).
        openfga_client = None
        if settings.access_control.ACCESS_CONTROL_BACKEND == "openfga":
            from agentarea_common.rebac.openfga_bootstrap import bootstrap_openfga
            from agentarea_common.rebac.openfga_client import OpenFGAClient

            if not settings.openfga.ACCESS_CONTROL_OPENFGA_API_TOKEN:
                logger.warning(
                    "ACCESS_CONTROL_OPENFGA_API_TOKEN is not set: OpenFGA calls are "
                    "unauthenticated. Set ACCESS_CONTROL_OPENFGA_API_TOKEN and the "
                    "server's OPENFGA_AUTHN_PRESHARED_KEYS to require a bearer token."
                )
            await bootstrap_openfga(settings.openfga)
            openfga_client = OpenFGAClient(
                api_url=settings.openfga.ACCESS_CONTROL_OPENFGA_API_URL,
                store_id=settings.openfga.ACCESS_CONTROL_OPENFGA_STORE_ID,
                authorization_model_id=settings.openfga.ACCESS_CONTROL_OPENFGA_AUTHORIZATION_MODEL_ID,
                timeout_seconds=settings.openfga.ACCESS_CONTROL_OPENFGA_TIMEOUT_SECONDS,
                api_token=settings.openfga.ACCESS_CONTROL_OPENFGA_API_TOKEN or None,
            )
            register_singleton(OpenFGAClient, openfga_client)

        keto_client = None
        if openfga_client is None and settings.access_control.ACCESS_CONTROL_BACKEND == "keto":
            from agentarea_common.rebac.keto_client import KetoClient

            keto_client = KetoClient(
                read_url=settings.keto.ACCESS_CONTROL_KETO_READ_URL,
                write_url=settings.keto.ACCESS_CONTROL_KETO_WRITE_URL,
                timeout_seconds=settings.keto.ACCESS_CONTROL_KETO_TIMEOUT_SECONDS,
            )
            register_singleton(KetoClient, keto_client)

        # PermissionService is a SELECTOR extension point: exactly one impl is
        # active, and an EXPLICIT ACCESS_CONTROL_BACKEND must win over a merely
        # installed "permissions" extension. (Previously the extension was checked
        # first and silently overrode the configured backend -- e.g. an installed
        # keto extension shadowed ACCESS_CONTROL_BACKEND=openfga so OpenFGA never
        # enforced.) The extension is a FALLBACK, used only when the operator did
        # not select a concrete backend. See AGENTS.md "Extension points".
        backend = settings.access_control.ACCESS_CONTROL_BACKEND
        perm_factory = ExtensionRegistry.get_factory("permissions")
        if openfga_client is not None:
            from agentarea_common.auth.openfga_permission import OpenFGAPermissionService

            register_singleton(PermissionService, OpenFGAPermissionService(openfga_client))
            perm_impl = "OpenFGAPermissionService"
        elif keto_client is not None:
            from agentarea_common.auth.keto_permission import KetoPermissionService

            register_singleton(PermissionService, KetoPermissionService(keto_client))
            perm_impl = "KetoPermissionService"
        elif perm_factory:
            register_factory(PermissionService, perm_factory)
            perm_impl = "extension:permissions"
        else:
            raise RuntimeError(
                "No PermissionService is available: ACCESS_CONTROL_BACKEND="
                f"{backend!r} selects no graph backend and no 'permissions' extension "
                "is installed. Refusing to start rather than falling back to an "
                "implementation that allows every check -- an authorization backend "
                "that is merely absent must not read as permission granted. Set "
                "ACCESS_CONTROL_BACKEND=openfga (or keto) and point it at a running "
                "instance."
            )

        if perm_factory and perm_impl != "extension:permissions":
            logger.warning(
                "Ignoring registered 'permissions' extension: ACCESS_CONTROL_BACKEND=%s "
                "selects %s explicitly. An extension cannot override an explicit backend.",
                backend,
                perm_impl,
            )
        logger.info("PermissionService=%s (ACCESS_CONTROL_BACKEND=%s)", perm_impl, backend)

        authz_factory = ExtensionRegistry.get_factory("authorization")
        if authz_factory:
            register_factory(AuthorizationService, authz_factory)
        else:
            register_singleton(AuthorizationService, WorkspaceScopedAuthorizationService())

        from agentarea_common.events.factory import create_event_broker

        event_broker = create_event_broker(settings.broker)
        register_singleton(EventBroker, event_broker)

        # Secret manager is created per-request with session and user_context
        # Not registered as singleton during startup
        # secret_manager = get_real_secret_manager()
        # register_singleton(BaseSecretManager, secret_manager)

        logger.info(
            "Real services initialized successfully - Event Broker: %s",
            type(event_broker).__name__,
        )
    except Exception as e:
        logger.exception("Service initialization failed: %s", e)
        raise e


async def cleanup_all_connections():
    """Comprehensive cleanup of all connections."""
    logger.info("Starting comprehensive connection cleanup...")

    try:
        # Cleanup connection manager singletons with timeout
        from agentarea_common.infrastructure.connection_manager import cleanup_connections

        await asyncio.wait_for(cleanup_connections(), timeout=2.0)
        logger.info("Connection manager cleanup completed")
    except TimeoutError:
        logger.warning("Connection manager cleanup timed out (reload mode)", exc_info=True)
    except Exception as e:
        logger.exception("Error in connection manager cleanup: %s", e)

    try:
        # Stop events router with timeout
        from agentarea_api.api.events.events_router import stop_events_router

        await asyncio.wait_for(stop_events_router(), timeout=2.0)
        logger.info("Events router cleanup completed")
    except TimeoutError:
        logger.warning("Events router cleanup timed out (reload mode)", exc_info=True)
    except Exception as e:
        logger.exception("Error in events router cleanup: %s", e)

    logger.info("All connection cleanup completed")


@asynccontextmanager
async def app_lifespan(app: FastAPI):
    """Original application lifespan."""
    import os

    # Detect if running with uvicorn reload
    is_reload_mode = os.getenv("RELOAD", "").lower() == "true" or "--reload" in " ".join(sys.argv)

    # NOTE: Don't override signal handlers - let uvicorn handle them for proper reload

    # Startup
    get_container()
    await initialize_services()

    from agentarea_api.api.events.events_router import start_events_router

    await start_events_router()

    logger.info("Application started successfully")

    try:
        yield
    finally:
        # Always stop the events router — Redis subscribers hold connections
        # open and block uvicorn reload if not cancelled
        from agentarea_api.api.events.events_router import stop_events_router

        await stop_events_router()

        if is_reload_mode:
            logger.info("Application shutting down (reload mode - skipping full cleanup)")
        else:
            logger.info("Application shutting down (production mode - full cleanup)")
            await cleanup_all_connections()


@asynccontextmanager
async def combined_lifespan(app: FastAPI):
    """Combined lifespan for app and FastAPI-MCP server."""
    async with app_lifespan(app):
        yield


# Security schemes for OpenAPI documentation
bearer_scheme = HTTPBearer(bearerFormat="JWT", description="JWT Bearer token for authentication")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    # Create MCP server — stateless_http=True means no session tracking
    # between requests, but the task group still needs to be initialised
    # via session_manager.run() in the lifespan.
    from agentarea_agents_sdk.mcp_server import (
        PinnedWorkspaceMiddleware,
        create_mcp_server,
        mount_mcp_app,
    )
    from agentarea_agents_sdk.mcp_server.auth import MCPAuthMiddleware
    from agentarea_agents_sdk.tools.base_tool import BaseTool
    from agentarea_agents_sdk.tools.decorator_tool import Toolset
    from mcp.server.transport_security import TransportSecuritySettings

    from agentarea_api.tools import get_platform_tools, get_spanning_mcp_tools

    _mcp_description = "AgentArea platform — agents, runs, MCP servers, providers, models, secrets"
    _transport_security = TransportSecuritySettings(enable_dns_rebinding_protection=False)
    # Bare /mcp spans every workspace the caller can reach: workspace-scoped
    # tools take a required `workspace` argument, found via workspaces_list.
    _mcp_server = create_mcp_server(
        toolsets=cast(list[Toolset | BaseTool], get_spanning_mcp_tools()),
        name="AgentArea",
        description=_mcp_description,
        workspace_argument=True,
    )
    _mcp_app = MCPAuthMiddleware(
        _mcp_server.streamable_http_app(
            streamable_http_path="/",
            stateless_http=True,
            transport_security=_transport_security,
        )
    )

    # /mcp/w/{workspace} pins one workspace by URL, so its tools carry no
    # `workspace` argument.
    _pinned_mcp_server = create_mcp_server(
        toolsets=cast(list[Toolset | BaseTool], get_platform_tools()),
        name="AgentArea",
        description=_mcp_description,
        workspace_argument=False,
    )
    _pinned_mcp_app = PinnedWorkspaceMiddleware(
        MCPAuthMiddleware(
            _pinned_mcp_server.streamable_http_app(
                streamable_http_path="/",
                stateless_http=True,
                transport_security=_transport_security,
            )
        ),
        prefix="/mcp/w",
    )

    from agentarea_api.api.v1.client_mcp import (
        ClientMCPScopeMiddleware,
        client_mcp_server,
    )

    _client_mcp_inner = MCPAuthMiddleware(
        client_mcp_server.streamable_http_app(
            streamable_http_path="/",
            stateless_http=True,
            transport_security=_transport_security,
        )
    )
    _client_mcp_app = ClientMCPScopeMiddleware(_client_mcp_inner, prefix="/mcp/clients")
    _legacy_client_mcp_app = ClientMCPScopeMiddleware(_client_mcp_inner, prefix="/client-mcp")

    @asynccontextmanager
    async def _lifespan(app: FastAPI):
        async with combined_lifespan(app):
            async with (
                _mcp_server.session_manager.run(),
                _pinned_mcp_server.session_manager.run(),
                client_mcp_server.session_manager.run(),
            ):
                yield

    app = FastAPI(
        title="AgentArea API",
        description=(
            "Modular and extensible framework for building AI agents. "
            "This API requires JWT Bearer token authentication for most "
            "endpoints. Include your JWT token in the Authorization header. "
            "Public endpoints include /, /health, /docs, /redoc, and "
            "/openapi.json."
        ),
        version="0.1.0",
        lifespan=_lifespan,
        openapi_tags=[
            {"name": "agents", "description": "Operations with AI agents"},
            {"name": "tasks", "description": "Operations with agent tasks"},
            {"name": "triggers", "description": "Operations with triggers"},
            {"name": "providers", "description": "Operations with LLM providers"},
            {"name": "models", "description": "Operations with LLM models"},
            {"name": "mcp", "description": "Operations with MCP servers"},
        ],
    )

    from agentarea_common.config import ObservabilitySettings
    from agentarea_common.observability import setup_otel

    observability_settings = ObservabilitySettings()
    if setup_otel("agentarea-api", observability_settings):
        _instrument_api(app)

    # Add audit context middleware (runs before route handlers)
    from agentarea_common.audit.middleware import AuditContextMiddleware

    app.add_middleware(AuditContextMiddleware)

    from agentarea_api.api.nul_character_middleware import NulCharacterMiddleware

    app.add_middleware(NulCharacterMiddleware)

    # Reject oversized request bodies (413) before buffering — cheap DoS guard.
    from agentarea_common.config import get_settings as _get_settings

    from agentarea_api.api.body_size_middleware import BodySizeLimitMiddleware

    app.add_middleware(
        BodySizeLimitMiddleware,
        max_bytes=_get_settings().app.MAX_REQUEST_BODY_BYTES,
    )

    # Add CORS middleware. Origins are an explicit allowlist (never "*"): with
    # allow_credentials=True a wildcard would reflect any origin for credentialed
    # cross-site reads. Configure via CORS_ALLOWED_ORIGINS.
    from agentarea_common.config import get_settings

    _cors = get_settings().app
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors.cors_allowed_origins,
        allow_origin_regex=_cors.CORS_ALLOWED_ORIGIN_REGEX,
        allow_credentials=_cors.CORS_ALLOW_CREDENTIALS,
        allow_methods=_cors.cors_allowed_methods,
        allow_headers=_cors.cors_allowed_headers,
        max_age=_cors.CORS_MAX_AGE,
    )

    # Mount static files - this serves all files from static/ at /static/
    static_path = Path(__file__).parent / "static"

    app.mount("/static", StaticFiles(directory=str(static_path)), name="static")

    # Add routers - PUBLIC routes first (no auth), then PROTECTED routes (auth required)
    # RFC 9728 OAuth AS metadata — no prefix so /.well-known/... is top-level
    app.include_router(oauth_as_router)

    # Webhook receiver — mounted outside /v1 to bypass auth middleware/dependencies
    # External services (Telegram, Slack, GitHub, etc.) POST to /webhooks/{id}
    from agentarea_api.api.v1 import webhooks as webhooks_module

    app.include_router(webhooks_module.router, tags=["webhooks"])

    app.include_router(public_v1_router, tags=["v1"])
    app.include_router(principal_v1_router, tags=["v1"])
    app.include_router(workspace_v1_router, tags=["v1"])
    app.include_router(a2a_v1_router, tags=["v1"])
    app.include_router(mcp_proxy_v1_router, tags=["v1"])

    # Routes contributed by installed extensions.
    #
    # The registry already lets a distribution replace a service implementation; this lets
    # one add endpoints, which is the other half of the same seam. It exists so a
    # deployment can serve routes this repository does not ship without forking the app
    # factory — the alternative being a fork whose only diff is one include_router call,
    # which then has to be rebased forever.
    #
    # Mounted last so an extension cannot shadow a core route by registering the same
    # path: FastAPI matches in insertion order, and the routes above are the contract this
    # project is responsible for.
    #
    # A failing extension must not take the API down with it. The registry is populated by
    # scanning installed packages, so a broken one is a deployment problem, and refusing
    # to start turns "one feature is unavailable" into "nothing is". A route that
    # breaks the workspace contract is different: it is a programming error, and
    # check_route_contract below refuses to build the app with it.
    from agentarea_common.extensions import discover_extensions
    from agentarea_common.extensions.registry import ExtensionRegistry

    # Discover here, not only in initialize_services().
    #
    # Routes have to exist on the app object before it starts serving, but
    # initialize_services() runs from the lifespan — after this function has
    # returned. So the registry was guaranteed empty at this line, get_factory
    # returned None, and the block below was skipped without logging anything:
    # an installed, working extension contributed nothing and said nothing.
    # (The `permissions` and `authorization` lookups are fine precisely because
    # they read the registry inside initialize_services, after discovery.)
    #
    # Calling it twice is harmless — ExtensionRegistry.register is a dict
    # assignment, so the later call re-registers the same factories.
    discover_extensions()

    # Two seams: ``api_router`` routes are mounted as declared (they act on no
    # workspace), ``workspace_api_router`` routes under /v1/workspaces/{workspace},
    # where the path selects the workspace they act in.
    for extension_point, prefix in (("api_router", ""), ("workspace_api_router", WORKSPACE_PREFIX)):
        extension_router_factory = ExtensionRegistry.get_factory(extension_point)
        if extension_router_factory is None:
            # Say so. The silence here is what let this ship broken: with no
            # extension installed this is the normal OSS path, but it is also what
            # a discovery-ordering bug looks like, and the two were indistinguishable.
            logger.info("No %s extension registered; serving core routes only", extension_point)
            continue
        try:
            extension_router = extension_router_factory()
        except Exception:
            logger.exception("%s extension failed to build; continuing without it", extension_point)
            continue
        if prefix:
            scoped = APIRouter(
                prefix=prefix,
                dependencies=workspace_v1_router.dependencies,
                generate_unique_id_function=workspace_v1_router.generate_unique_id_function,
            )
            scoped.include_router(extension_router)
            extension_router = scoped
        app.include_router(extension_router)
        logger.info("Mounted routes from the %s extension", extension_point)

    # Mount native MCP server at /mcp — exposes platform tools via MCP protocol.
    # Auth: Hydra OAuth tokens (Cursor/Claude Desktop), API keys, Kratos JWT.
    # Session manager lifespan is run in _lifespan (above) so the task group
    # is guaranteed to be initialised before any request reaches the handler.
    # mount_mcp_app, not app.mount: the bare /mcp form is the resource identifier
    # we advertise, so it has to be served rather than redirected to /mcp/.
    # The sub-mounts go first: Starlette matches in order, and /mcp would
    # otherwise swallow /mcp/w/... and /mcp/clients/....
    app.mount("/mcp/w", _pinned_mcp_app)
    app.mount("/mcp/clients", _client_mcp_app)
    app.mount("/client-mcp", _legacy_client_mcp_app)
    mount_mcp_app(app, "/mcp", _mcp_app)

    _tool_count = sum(len(ts._tool_methods) for ts in get_platform_tools())
    logger.info("Native MCP server mounted at /mcp with %d platform tools", _tool_count)

    # Register the unified error handlers (RFC 9457 problem+json): AppError,
    # PermissionError, validation, HTTPException, DB integrity, and a catch-all
    # so no response is ever a non-JSON body.
    register_error_handlers(app)

    # Map the domain BudgetCapExceededError to HTTP 402 Payment Required. The
    # domain exception stays free of web concerns; the composition layer renders
    # it via the shared problem+json helper, surfacing the numbers so the UI can
    # show "you've spent $X of $Y, raise the cap or wait".
    from agentarea_agents.application.agent_service import InvalidModelIdError
    from agentarea_agents.application.approval_sync import ApprovalEnforcedByPolicyError
    from agentarea_common.exceptions import problem_response
    from agentarea_common.rebac import ResourceOwnershipError
    from agentarea_llm.application.provider_service import PlatformManagedConfigError
    from agentarea_tasks.domain.exceptions import BudgetCapExceededError
    from fastapi import Request

    # A model_id the runtime cannot resolve is a client mistake, not a server
    # fault: the service rejects it on write so it can no longer surface as a
    # workflow failure hours later.
    @app.exception_handler(InvalidModelIdError)
    async def _invalid_model_id_handler(_request: Request, exc: InvalidModelIdError):
        return problem_response(
            status_code=400,
            code="invalid_model_id",
            detail=str(exc),
        )

    # Only a workspace admin may untick an approval rule the agent editor's toggle
    # did not write. 409 so the editor can say who may change it.
    @app.exception_handler(ApprovalEnforcedByPolicyError)
    async def _approval_enforced_handler(_request: Request, exc: ApprovalEnforcedByPolicyError):
        return problem_response(
            status_code=409,
            code="approval_enforced_by_policy",
            detail=str(exc),
            extra={"targets": sorted(exc.targets)},
        )

    # A configuration the deployment supplies is readable from every workspace so
    # its models can be used without a key. 403 rather than 404: the caller can see
    # the row in their own listing, and answering "no such configuration" about
    # something they are looking at reads as a bug in us rather than a rule.
    @app.exception_handler(PlatformManagedConfigError)
    async def _platform_managed_config_handler(_request: Request, exc: PlatformManagedConfigError):
        return problem_response(
            status_code=403,
            code="platform_managed_config",
            detail=str(exc),
        )

    # A row committed without its ownership tuples is unreachable to everyone,
    # including whoever just created it. 503 rather than 500: the grant is
    # idempotent, so repeating the request is the right response.
    @app.exception_handler(ResourceOwnershipError)
    async def _resource_ownership_handler(_request: Request, exc: ResourceOwnershipError):
        return problem_response(
            status_code=503,
            code="resource_ownership_unavailable",
            detail=str(exc),
        )

    @app.exception_handler(BudgetCapExceededError)
    async def _budget_cap_exceeded_handler(_request: Request, exc: BudgetCapExceededError):
        return problem_response(
            status_code=402,
            code="budget_cap_exceeded",
            detail=str(exc),
            extra={
                "current_mtd_usd": exc.current_mtd_usd,
                "cap_usd": exc.cap_usd,
                "workspace_id": exc.workspace_id,
            },
        )

    # Health check endpoint
    @app.get("/health", dependencies=[unrestricted("liveness probe, returns no workspace data")])
    async def health():
        """Health check endpoint."""
        return {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
        }

    # A route that names no workspace yet resolves one would fail every request
    # it serves; refuse to build instead. Extension routes are checked too.
    check_route_contract(app.routes)

    # Customize OpenAPI: add bearer scheme and ensure per-operation security
    def custom_openapi():
        if app.openapi_schema:
            return app.openapi_schema

        openapi_schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
        )

        # Define security schemes
        openapi_schema.setdefault("components", {}).setdefault("securitySchemes", {})
        openapi_schema["components"]["securitySchemes"]["bearer"] = {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "JWT Bearer token for authentication",
        }

        # Apply global security and ensure operation-level security
        # Skip /mcp/* routes (MCP proxy endpoints handle their own auth)
        default_security = [{"bearer": []}]
        openapi_schema["security"] = default_security
        for path, path_item in openapi_schema.get("paths", {}).items():
            # Skip MCP proxy routes - they handle auth differently
            if path.startswith("/mcp"):
                continue
            for method in ("get", "post", "put", "delete", "patch", "options", "head"):
                op = path_item.get(method)
                if op and "security" not in op:
                    op["security"] = default_security

        app.openapi_schema = openapi_schema
        return app.openapi_schema

    app.openapi = custom_openapi

    return app


def _instrument_api(app: FastAPI) -> None:
    """Install OpenTelemetry instrumentation for API process dependencies."""
    from opentelemetry.instrumentation.asyncpg import AsyncPGInstrumentor
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from opentelemetry.instrumentation.redis import RedisInstrumentor

    FastAPIInstrumentor.instrument_app(app)
    AsyncPGInstrumentor().instrument()
    RedisInstrumentor().instrument()
    HTTPXClientInstrumentor().instrument()


app = create_app()


@app.get("/", dependencies=[unrestricted("service banner, returns no workspace data")])
async def root():
    """Root endpoint."""
    return {"message": "AgentArea API is running."}


@app.get("/health", dependencies=[unrestricted("liveness probe, returns no workspace data")])
async def health_check():
    """Health check endpoint for the main application."""
    from agentarea_common.infrastructure.connection_manager import get_connection_health

    connection_health = await get_connection_health()

    return {
        "status": "healthy",
        "service": "agentarea-api",
        "version": "0.1.0",
        "connections": connection_health,
        "timestamp": datetime.now().isoformat(),
    }


# reload test
