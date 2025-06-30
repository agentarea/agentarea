"""Main FastAPI application for AgentArea."""

# from agentarea_api.api.events.mcp_events import register_mcp_event_handlers
# from agentarea_common.config import get_settings
from contextlib import asynccontextmanager

# Dependency injection container setup
from agentarea_common.di.container import DIContainer, register_singleton
from agentarea_common.events.broker import EventBroker

# from agentarea_common.events.base_events import DomainEvent  # Removed - not used
from agentarea_common.infrastructure.secret_manager import BaseSecretManager
from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from agentarea_api.api.deps.services import get_event_broker, get_secret_manager
from agentarea_api.api.events import events_router
from agentarea_api.api.v1.router import v1_router

container = DIContainer()


# Use real service implementations instead of test mocks
async def initialize_services():
    """Initialize real services instead of test mocks."""
    try:
        # Get real event broker (Redis-based with fallback)
        event_broker = await get_event_broker()
        register_singleton(EventBroker, event_broker)

        # Get real secret manager (Infisical-based with fallback)
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
    # Startup
    await initialize_services()

    # Start the FastStream events router
    from agentarea_api.api.events.events_router import start_events_router

    await start_events_router()

    print("Application started successfully")
    yield
    # Shutdown
    print("Application shutting down")

    # Stop the FastStream events router
    from agentarea_api.api.events.events_router import stop_events_router

    await stop_events_router()


app = FastAPI(
    title="AgentArea API",
    description="Modular and extensible framework for building AI agents.",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
# app.mount("/static", StaticFiles(directory="static"), name="static")

# API routers
app.include_router(v1_router)

# Include events router to handle task events
app.include_router(events_router)


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
