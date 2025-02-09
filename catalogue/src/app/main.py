from fastapi import FastAPI
from .routers import module

app = FastAPI(title="AI Agent Service")

app.include_router(module.router)
