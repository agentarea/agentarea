from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agentarea.api.v1.router import v1_router
from agentarea.api.events.events_router import router as events_router
from agentarea.common.events.router import create_event_broker_from_router
from agentarea.common.events.broker import EventBroker
from agentarea.common.di.container import register_singleton


# Application state for managing singletons
class AppState:
    event_broker: EventBroker | None = None


app_state = AppState()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan - startup and shutdown events."""
    # Startup
    try:
        # Try to create EventBroker from the router's broker (for Redis/Kafka)
        event_broker = create_event_broker_from_router(events_router)
        app_state.event_broker = event_broker
    except ValueError:
        # Fallback to Redis EventBroker (concrete implementation)
        from agentarea.common.events.redis_event_broker import RedisEventBroker
        from faststream.redis import RedisBroker
        from agentarea.config import get_settings, RedisSettings
        
        # Create a RedisBroker instance for the fallback
        broker_settings = get_settings().broker
        if isinstance(broker_settings, RedisSettings):
            redis_broker = RedisBroker(broker_settings.REDIS_URL)
        else:
            # Default fallback to localhost Redis
            redis_broker = RedisBroker("redis://localhost:6379")
        event_broker = RedisEventBroker(redis_broker)
        app_state.event_broker = event_broker
    
    # Register with DI container as well (alternative pattern)
    register_singleton(EventBroker, event_broker)
    
    # Log successful startup
    import logging
    logger = logging.getLogger(__name__)
    logger.info("Application started successfully with event broker configured")
    
    yield
    
    # Shutdown - cleanup if needed
    app_state.event_broker = None


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        lifespan=lifespan, 
        title="AgentArea API", 
        description="Agent management and orchestration platform",
        version="1.0.0"
    )
    
    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Include routers
    app.include_router(v1_router)
    app.include_router(events_router)
    
    return app


# Create the app instance
app = create_app()
