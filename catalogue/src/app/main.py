from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .routers import module, source, source_specification

app = FastAPI(title="AI Agent Service")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # Add your frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(module.router)
app.include_router(source.router)
app.include_router(source_specification.router)
