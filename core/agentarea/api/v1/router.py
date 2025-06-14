from fastapi import APIRouter

from . import (
    agents,
    agents_tasks,
    llm_model_instances,
    llm_models_specifications,
    mcp_server_instances,
    mcp_servers_specifications,
)
# Tasks endpoints
from . import tasks

v1_router = APIRouter(prefix="/v1")
v1_router.include_router(agents.router)
v1_router.include_router(agents_tasks.router)
v1_router.include_router(llm_models_specifications.router)
v1_router.include_router(llm_model_instances.router)
v1_router.include_router(mcp_servers_specifications.router)
v1_router.include_router(mcp_server_instances.router)
# Include tasks router
v1_router.include_router(tasks.router)
