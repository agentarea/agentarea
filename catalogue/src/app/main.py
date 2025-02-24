from fastapi import FastAPI
from .routers import v1_router

app = FastAPI(title="AI Agent Service")

app.include_router(v1_router())
