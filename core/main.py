"""
Main FastAPI application with static file serving
"""
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from core.api.routes.providers import router as providers_router
from core.api.routes.mcp import router as mcp_router
from core.agentarea.api.v1.mcp_server_instances_enhanced import router as mcp_enhanced_router

# Create FastAPI app
app = FastAPI(
    title="AgentArea API",
    description="API for AI providers, models, and MCP servers",
    version="1.0.0"
)

# Mount static files - this serves all files from core/static/ at /static/
app.mount("/static", StaticFiles(directory="core/static"), name="static")

# Include API routes
app.include_router(providers_router, prefix="/api/v1", tags=["providers"])
app.include_router(mcp_router, prefix="/api/v1", tags=["mcp"])
app.include_router(mcp_enhanced_router, prefix="/api/v1/mcp/instances", tags=["mcp-enhanced"])

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "AgentArea API",
        "version": "1.0.0",
        "endpoints": {
            "providers": "/api/v1/providers",
            "mcp": "/api/v1/mcp",
            "mcp_instances": "/api/v1/mcp/instances",
            "static_files": "/static/",
            "icons": "/static/icons/providers/"
        }
    } 