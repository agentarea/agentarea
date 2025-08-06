"""Main FastAPI application for AgentArea."""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from agentarea_common.auth.middleware import AuthMiddleware
from agentarea_common.di.container import get_container, register_singleton
from agentarea_common.events.broker import EventBroker
from agentarea_common.exceptions.registration import register_workspace_error_handlers
from agentarea_common.infrastructure.secret_manager import BaseSecretManager
from agentarea_secrets import get_real_secret_manager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.security import HTTPBearer
from fastapi.staticfiles import StaticFiles

from agentarea_api.api.events import events_router
from agentarea_api.api.v1.router import v1_router

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

        secret_manager = get_real_secret_manager()
        register_singleton(BaseSecretManager, secret_manager)

        print(
            f"Real services initialized successfully - "
            f"Event Broker: {type(event_broker).__name__}, "
            f"Secret Manager: {type(secret_manager).__name__}"
        )
    except Exception as e:
        print(f"ERROR: Service initialization failed: {e}")
        raise e


@asynccontextmanager
async def lifespan(app: FastAPI):
    # await startup_handler()
    container = get_container()
    await initialize_services()

    from agentarea_api.api.events.events_router import start_events_router
    await start_events_router()

    print("Application started successfully")
    yield

    print("Application shutting down")

    from agentarea_api.api.events.events_router import stop_events_router
    await stop_events_router()
    # Note: DIContainer doesn't need explicit shutdown


# Security schemes for OpenAPI documentation
bearer_scheme = HTTPBearer(
    bearerFormat="JWT",
    description="JWT Bearer token for authentication"
)

workspace_header_scheme = {
    "type": "apiKey",
    "in": "header",
    "name": "X-Workspace-ID",
    "description": "Workspace ID for data isolation"
}

# Global security requirement
security_requirements = [
    {"bearer": []},
    {"workspace_header": []}
]


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="AgentArea API",
        description="Modular and extensible framework for building AI agents. This API requires JWT Bearer token authentication for most endpoints. Include your JWT token in the Authorization header and workspace ID in the X-Workspace-ID header. Public endpoints include /, /health, /docs, /redoc, and /openapi.json. In development mode, use X-Dev-User-ID header to bypass authentication.",
        version="0.1.0",
        lifespan=lifespan,
        openapi_tags=[
            {
                "name": "agents",
                "description": "Operations with AI agents"
            },
            {
                "name": "tasks",
                "description": "Operations with agent tasks"
            },
            {
                "name": "triggers",
                "description": "Operations with triggers"
            },
            {
                "name": "providers",
                "description": "Operations with LLM providers"
            },
            {
                "name": "models",
                "description": "Operations with LLM models"
            },
            {
                "name": "mcp",
                "description": "Operations with MCP servers"
            },
            {
                "name": "development",
                "description": "Development utilities (only available in dev mode)"
            }
        ]
    )

    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Add authentication middleware
    app.add_middleware(
        AuthMiddleware,
        provider_name="clerk",
        config={
            "CLERK_SECRET_KEY": os.getenv("CLERK_SECRET_KEY", ""),
            "CLERK_ISSUER": os.getenv("CLERK_ISSUER", ""),
            "CLERK_JWKS_URL": os.getenv("CLERK_JWKS_URL", ""),
            "CLERK_AUDIENCE": os.getenv("CLERK_AUDIENCE", ""),
        }
    )

    # Mount static files - this serves all files from static/ at /static/
    static_path = Path(__file__).parent / "static"

    app.mount("/static", StaticFiles(directory=str(static_path)), name="static")
    # Add routers
    app.include_router(events_router, prefix="/events", tags=["events"])
    app.include_router(v1_router, tags=["v1"])

    # Register workspace error handlers
    register_workspace_error_handlers(app)

    # Development endpoints (only in dev mode)
    dev_mode = os.getenv("DEV_MODE", "false").lower() == "true"

    if dev_mode:
        @app.get("/dev/token", tags=["development"])
        async def get_dev_token():
            """Development mode information."""
            return {
                "message": "Development mode is enabled. No authentication required.",
                "usage": {
                    "user_id": "dev-user",
                    "workspace_id": "default",
                    "example": "curl http://localhost:8000/v1/agents/"
                }
            }

    # Add security schemes to OpenAPI
    app.openapi_schema = None  # Force regeneration
    if app.openapi_schema is None:
        app.openapi_schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
        )
        app.openapi_schema["components"]["securitySchemes"] = {
            "bearer": {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "JWT",
                "description": "JWT Bearer token for authentication"
            },
            "workspace_header": {
                "type": "apiKey",
                "in": "header",
                "name": "X-Workspace-ID",
                "description": "Workspace ID for data isolation"
            }
        }
        app.openapi_schema["security"] = [
            {"bearer": []},
            {"workspace_header": []}
        ]

    return app


app = create_app()


@app.get("/")
async def root():
    """Root endpoint."""
    return {"message": "AgentArea API is running."}


@app.get("/health")
async def health_check():
    """Health check endpoint for the main application."""
    return {
        "status": "healthy",
        "service": "agentarea-api",
        "version": "0.1.0",
    }
