"""Main FastAPI application for AgentArea."""

import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from agentarea_common.di.container import get_container, register_singleton
from agentarea_common.events.broker import EventBroker
from agentarea_common.exceptions.registration import register_workspace_error_handlers
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.security import HTTPBearer
from fastapi.staticfiles import StaticFiles
from fastapi_mcp import AuthConfig, FastApiMCP

from agentarea_api.api.events import events_router
from agentarea_api.api.v1.router import protected_v1_router, public_v1_router

logger = logging.getLogger(__name__)
container = get_container()

# Cache auth provider to avoid recreating it on every request
_mcp_auth_provider = None


def _get_mcp_auth_provider():
    """Get or create the MCP auth provider (cached singleton).

    This avoids recreating the provider and decoding JWKS on every request.
    """
    global _mcp_auth_provider

    if _mcp_auth_provider is not None:
        return _mcp_auth_provider

    from agentarea_common.auth.providers.factory import AuthProviderFactory
    from agentarea_common.config.app import get_app_settings

    settings = get_app_settings()
    _mcp_auth_provider = AuthProviderFactory.create_provider(
        "kratos",
        config={
            "jwks_b64": settings.KRATOS_JWKS_B64,
            "issuer": settings.KRATOS_ISSUER,
            "audience": settings.KRATOS_AUDIENCE,
        },
    )

    logger.info("MCP auth provider initialized (cached for performance)")
    return _mcp_auth_provider


async def verify_mcp_auth(request: Request) -> None:
    """Verify MCP authentication via JWT Bearer token.

    Validates JWT tokens using the cached auth provider (e.g., Kratos).
    Requires Authorization header with format: 'Bearer <jwt_token>'

    Args:
        request: FastAPI request object

    Raises:
        HTTPException: If authentication fails (missing token, invalid token, etc.)
    """
    auth_header = request.headers.get("Authorization", "")

    # Check for Bearer token
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid Authorization header. Expected: 'Bearer <token>'",
        )

    token = auth_header[7:]  # Remove "Bearer " prefix

    try:
        # Get cached auth provider (avoids recreating on every request)
        auth_provider = _get_mcp_auth_provider()

        # Verify the JWT token
        auth_result = await auth_provider.verify_token(token)

        if not auth_result.is_authenticated or not auth_result.token:
            logger.warning(f"MCP JWT validation failed: {auth_result.error}")
            raise HTTPException(
                status_code=401,
                detail="Invalid or expired authentication token",
            )

        # Token is valid - add user info to request state for downstream use
        request.state.user_id = auth_result.token.user_id
        if auth_result.token.claims:
            request.state.workspace_id = auth_result.token.claims.get("workspace_id")

        logger.debug(f"MCP authentication successful for user: {auth_result.token.user_id}")

    except HTTPException:
        # Re-raise HTTPException as-is
        raise
    except Exception as e:
        logger.error(f"Unexpected error during MCP JWT validation: {e}")
        raise HTTPException(
            status_code=401,
            detail="Authentication validation failed",
        ) from e


async def initialize_services():
    """Initialize real services instead of test mocks."""
    try:
        from agentarea_common.config import get_settings
        from agentarea_common.events.router import create_event_broker_from_router, get_event_router

        settings = get_settings()
        event_router = get_event_router(settings.broker)
        event_broker = create_event_broker_from_router(event_router)
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
        logger.error("Service initialization failed: %s", e)
        raise e


async def cleanup_all_connections():
    """Comprehensive cleanup of all connections."""
    logger.info("🧹 Starting comprehensive connection cleanup...")

    try:
        # Cleanup connection manager singletons with timeout
        from agentarea_common.infrastructure.connection_manager import cleanup_connections

        await asyncio.wait_for(cleanup_connections(), timeout=2.0)
        logger.info("✅ Connection manager cleanup completed")
    except TimeoutError:
        logger.warning("⚠️  Connection manager cleanup timed out (reload mode)")
    except Exception as e:
        logger.error("⚠️  Error in connection manager cleanup: %s", e)

    try:
        # Stop events router with timeout
        from agentarea_api.api.events.events_router import stop_events_router

        await asyncio.wait_for(stop_events_router(), timeout=2.0)
        logger.info("✅ Events router cleanup completed")
    except TimeoutError:
        logger.warning("⚠️  Events router cleanup timed out (reload mode)")
    except Exception as e:
        logger.error("⚠️  Error in events router cleanup: %s", e)

    logger.info("🎉 All connection cleanup completed")


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
        # Shutdown - skip cleanup in reload mode for fast restarts
        if is_reload_mode:
            logger.info("Application shutting down (reload mode - skipping cleanup)")
        else:
            logger.info("Application shutting down (production mode - full cleanup)")
            await cleanup_all_connections()


@asynccontextmanager
async def combined_lifespan(app: FastAPI):
    """Combined lifespan for app and FastAPI-MCP server."""
    # Run app lifespan - FastAPI-MCP is integrated directly
    async with app_lifespan(app):
        yield


# Security schemes for OpenAPI documentation
bearer_scheme = HTTPBearer(bearerFormat="JWT", description="JWT Bearer token for authentication")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
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
        lifespan=combined_lifespan,
        openapi_tags=[
            {"name": "agents", "description": "Operations with AI agents"},
            {"name": "tasks", "description": "Operations with agent tasks"},
            {"name": "triggers", "description": "Operations with triggers"},
            {"name": "providers", "description": "Operations with LLM providers"},
            {"name": "models", "description": "Operations with LLM models"},
            {"name": "mcp", "description": "Operations with MCP servers"},
        ],
    )

    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Mount static files - this serves all files from static/ at /static/
    static_path = Path(__file__).parent / "static"

    app.mount("/static", StaticFiles(directory=str(static_path)), name="static")

    # Add routers - PUBLIC routes first (no auth), then PROTECTED routes (auth required)
    app.include_router(events_router, prefix="/events", tags=["events"])
    app.include_router(public_v1_router, tags=["v1"])
    app.include_router(protected_v1_router, tags=["v1"])

    mcp_server = FastApiMCP(
        app,
        auth_config=AuthConfig(
            dependencies=[Depends(verify_mcp_auth)],
        ),
    )
    # Mount HTTP MCP server at /mcp endpoint
    # Accepts JSON-RPC 2.0 requests with streamable-http transport
    mcp_server.mount_http()

    logger.info("FastAPI-MCP server mounted at /mcp with authentication enabled")

    # Register workspace error handlers
    register_workspace_error_handlers(app)

    # Health check endpoint
    @app.get("/health")
    async def health():
        """Health check endpoint."""
        return {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
        }

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
        default_security = [{"bearer": []}]
        openapi_schema["security"] = default_security
        for path_item in openapi_schema.get("paths", {}).values():
            for method in ("get", "post", "put", "delete", "patch", "options", "head"):
                op = path_item.get(method)
                if op and "security" not in op:
                    op["security"] = default_security

        app.openapi_schema = openapi_schema
        return app.openapi_schema

    app.openapi = custom_openapi

    return app


app = create_app()


@app.get("/")
async def root():
    """Root endpoint."""
    return {"message": "AgentArea API is running."}


@app.get("/health")
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
