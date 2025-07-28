"""Main FastAPI application for AgentArea."""

from contextlib import asynccontextmanager
from pathlib import Path

from agentarea_common.di.container import DIContainer, get_container, register_singleton
from agentarea_common.events.broker import EventBroker
from agentarea_common.events.router import get_event_router
from agentarea_common.exceptions.registration import register_workspace_error_handlers
from agentarea_common.infrastructure.secret_manager import BaseSecretManager
from agentarea_secrets import get_real_secret_manager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.cors import CORSMiddleware

from agentarea_api.api.events import events_router
from agentarea_api.api.v1.router import v1_router
# from agentarea_api.api.jwt_middleware import JWTMiddleware
from agentarea_common.auth.middleware import AuthMiddleware

container = DIContainer()


async def initialize_services():
    """Initialize real services instead of test mocks."""
    try:
        from agentarea_common.config import get_settings
        from agentarea_common.events.router import create_event_broker_from_router

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


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="AgentArea API",
        description="Modular and extensible framework for building AI agents.",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Get settings for JWT configuration
    from agentarea_common.config import get_settings
    settings = get_settings()

    # Add Clerk authentication middleware
    app.add_middleware(
        AuthMiddleware,
        provider_name="clerk",
        config={
            "jwks_url": f"{settings.app.CLERK_ISSUER}/.well-known/jwks.json",
            "issuer": settings.app.CLERK_ISSUER,
        }
    )

    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Add static file serving for provider icons
    static_path = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_path)), name="static")

    # Register workspace error handlers
    register_workspace_error_handlers(app)

    # Include API router
    app.include_router(v1_router)
    app.include_router(events_router)

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
