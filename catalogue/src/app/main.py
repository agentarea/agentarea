from fastapi import FastAPI
from .routers import agents

app = FastAPI(title="AI Agent Service")

app.include_router(agents.router)
