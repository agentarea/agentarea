"""
Main FastAPI application with static file serving
"""
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from core.api.routes.providers import router as providers_router

# Create FastAPI app
app = FastAPI(
    title="AgentArea API",
    description="API for AI providers and models",
    version="1.0.0"
)

# Mount static files - this serves all files from core/static/ at /static/
app.mount("/static", StaticFiles(directory="core/static"), name="static")

# Include API routes
app.include_router(providers_router, prefix="/api/v1", tags=["providers"])

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "AgentArea API",
        "version": "1.0.0",
        "endpoints": {
            "providers": "/api/v1/providers",
            "static_files": "/static/",
            "icons": "/static/icons/providers/"
        }
    } 