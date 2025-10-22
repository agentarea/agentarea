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
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.security import HTTPBearer
from fastapi.staticfiles import StaticFiles

from agentarea_api.api.events import events_router

# Import MCP server
from agentarea_api.api.v1.mcp import mcp_app
from agentarea_api.api.v1.router import protected_v1_router, public_v1_router

logger = logging.getLogger(__name__)
container = get_container()


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

        print(
            f"Real services initialized successfully - "
            f"Event Broker: {type(event_broker).__name__}"
        )
    except Exception as e:
        print(f"ERROR: Service initialization failed: {e}")
        raise e


async def cleanup_all_connections():
    """Comprehensive cleanup of all connections."""
    print("🧹 Starting comprehensive connection cleanup...")

    try:
        # Cleanup connection manager singletons with timeout
        from agentarea_common.infrastructure.connection_manager import cleanup_connections

        await asyncio.wait_for(cleanup_connections(), timeout=2.0)
        print("✅ Connection manager cleanup completed")
    except asyncio.TimeoutError:
        print("⚠️  Connection manager cleanup timed out (reload mode)")
    except Exception as e:
        print(f"⚠️  Error in connection manager cleanup: {e}")

    try:
        # Stop events router with timeout
        from agentarea_api.api.events.events_router import stop_events_router

        await asyncio.wait_for(stop_events_router(), timeout=2.0)
        print("✅ Events router cleanup completed")
    except asyncio.TimeoutError:
        print("⚠️  Events router cleanup timed out (reload mode)")
    except Exception as e:
        print(f"⚠️  Error in events router cleanup: {e}")

    print("🎉 All connection cleanup completed")


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

    print("Application started successfully")

    try:
        yield
    finally:
        # Shutdown - skip cleanup in reload mode for fast restarts
        if is_reload_mode:
            print("Application shutting down (reload mode - skipping cleanup)")
        else:
            print("Application shutting down (production mode - full cleanup)")
            await cleanup_all_connections()


@asynccontextmanager
async def combined_lifespan(app: FastAPI):
    """Combined lifespan for app and MCP server."""
    # Run both lifespans - app first, then MCP
    async with app_lifespan(app):
        async with mcp_app.lifespan(app):
            yield


# Security schemes for OpenAPI documentation
bearer_scheme = HTTPBearer(bearerFormat="JWT", description="JWT Bearer token for authentication")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="AgentArea API",
        description="Modular and extensible framework for building AI agents. This API requires JWT Bearer token authentication for most endpoints. Include your JWT token in the Authorization header. Public endpoints include /, /health, /docs, /redoc, and /openapi.json.",
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
    app.mount("/llm", mcp_app)

    # Add routers - PUBLIC routes first (no auth), then PROTECTED routes (auth required)
    app.include_router(events_router, prefix="/events", tags=["events"])
    app.include_router(public_v1_router, tags=["v1", "public"])
    app.include_router(protected_v1_router, tags=["v1", "protected"])

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
