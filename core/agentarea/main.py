from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agentarea.api.v1.router import v1_router
from agentarea.config import get_settings


def create_app() -> FastAPI:
    app = FastAPI(
        title="AgentArea",
        description="Agent management and orchestration platform",
        version="1.0.0",
    )

    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include API routes
    app.include_router(v1_router)

    return app


app = create_app()
