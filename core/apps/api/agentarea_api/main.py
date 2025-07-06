"""Main FastAPI application for AgentArea."""

from contextlib import asynccontextmanager
from pathlib import Path

from agentarea_common.di.container import DIContainer, register_singleton, get_container
from agentarea_common.events.broker import EventBroker
from agentarea_common.infrastructure.secret_manager import BaseSecretManager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.cors import CORSMiddleware

from agentarea_api.api.deps.services import get_event_broker, get_secret_manager
from agentarea_api.api.events import events_router
from agentarea_api.api.v1.router import v1_router
from agentarea_api.startup import startup_event

container = DIContainer()


async def initialize_services():
    """Initialize real services instead of test mocks."""
    try:
        event_broker = await get_event_broker()
        register_singleton(EventBroker, event_broker)

        secret_manager = await get_secret_manager()
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
    await container.shutdown_resources()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="AgentArea API",
        description="Modular and extensible framework for building AI agents.",
        version="0.1.0",
        lifespan=lifespan,
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
