from fastapi import APIRouter, Depends
from .dependencies import get_model_service
from .model import router as model_router
from .module import router as module_router
from .source import router as source_router
from .source_specification import router as source_specification_router
from .tools import router as tools_router


def v1_router():
    router = APIRouter(prefix="")
    router.include_router(
        model_router, prefix="/models", dependencies=[Depends(get_model_service)]
    )
    router.include_router(module_router, prefix="/modules")
    router.include_router(source_router)
    router.include_router(source_specification_router)
    router.include_router(tools_router, prefix="/tools")
    return router
