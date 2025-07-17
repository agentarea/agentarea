from fastapi import APIRouter

# Import core API modules
from . import (
    agents,
    agents_tasks,
    chat,
    mcp_server_instances,
    mcp_servers_specifications,
    model_instances_new,
    model_specs,
    provider_configs,
    provider_specs,
    well_known,
)

v1_router = APIRouter(prefix="/v1")

# Well-known endpoints are included at the root level in main.py

# Include chat router (unified chat interface)
v1_router.include_router(chat.router)

# Include core API routers
v1_router.include_router(agents.router)
v1_router.include_router(agents_tasks.router)
v1_router.include_router(agents_tasks.global_tasks_router)
v1_router.include_router(mcp_servers_specifications.router)
v1_router.include_router(mcp_server_instances.router)

# Include LLM architecture routers (4-entity system)
v1_router.include_router(provider_specs.router)
v1_router.include_router(provider_configs.router)
v1_router.include_router(model_specs.router)
v1_router.include_router(model_instances_new.router)
