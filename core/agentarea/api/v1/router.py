from fastapi import APIRouter

from . import agents, llm_models_specifications, llm_model_instances, mcp_server_instances, mcp_servers_specifications

v1_router = APIRouter(prefix="/v1")
v1_router.include_router(agents.router)
v1_router.include_router(mcp_servers_specifications.router)
v1_router.include_router(mcp_server_instances.router)
v1_router.include_router(llm_models_specifications.router)
v1_router.include_router(llm_model_instances.router)
