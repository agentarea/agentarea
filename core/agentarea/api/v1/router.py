from fastapi import APIRouter

# Unified protocol endpoint (A2A compliant + REST API)
from . import protocol

# Unified chat interface (consolidates A2A and REST chat functionality)
from . import chat

# Core API modules
from . import (
    agents,
    agents_tasks,
    llm_model_instances,
    llm_models_specifications,
    mcp_server_instances,
    mcp_servers_specifications,
)

# Removed unified LLM router - using proper service patterns instead

v1_router = APIRouter(prefix="/v1")

# Include unified protocol router first (primary A2A interface) 
v1_router.include_router(protocol.router)

# Include unified chat router (consolidates all chat functionality)
v1_router.include_router(chat.router)

# Include core API routers
v1_router.include_router(agents.router)
v1_router.include_router(agents_tasks.router)
v1_router.include_router(llm_models_specifications.router)
v1_router.include_router(llm_model_instances.router)
v1_router.include_router(mcp_servers_specifications.router)
v1_router.include_router(mcp_server_instances.router)

# LLM execution now properly integrated through existing services
