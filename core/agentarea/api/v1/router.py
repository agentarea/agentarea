from fastapi import APIRouter
from . import agents

v1_router = APIRouter(prefix="/v1")
v1_router.include_router(agents.router) 