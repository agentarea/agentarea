from fastapi import APIRouter

from . import agents

v1_router = APIRouter(prefix="/v1")
v1_router.include_router(agents.router)
# v1_router.include_router(mcp_servers.router)
# v1_router.include_router(llm_models.router)
# v1_router.include_router(llm_model_instances.router)
