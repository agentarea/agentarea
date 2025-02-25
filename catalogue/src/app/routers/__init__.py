from fastapi import APIRouter, Depends
from .dependencies import get_llm_service
from .llm import router as llm_router
from .module import router as module_router
from .source import router as source_router
from .source_specification import router as source_specification_router


def v1_router():
    router = APIRouter(prefix="/v1/catalog")
    router.include_router(
        llm_router, prefix="/llms", dependencies=[Depends(get_llm_service)]
    )
    router.include_router(module_router, prefix="/modules")
    router.include_router(source_router, prefix="/sources")
    router.include_router(source_specification_router, prefix="/source_specifications")
    return router
