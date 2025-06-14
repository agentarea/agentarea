"""
API router configuration for AgentArea platform.

This module configures the main API router and includes all endpoint routers
for the v1 API.
"""

from fastapi import APIRouter

from agentarea.api.v1.endpoints import tasks
# Import other endpoint modules as needed
# from agentarea.api.v1.endpoints import agents, llm, mcp, etc.

# Main API router for v1
api_router = APIRouter()

# Include all endpoint routers
api_router.include_router(tasks.router)

# Include other routers as they become available
# api_router.include_router(agents.router)
# api_router.include_router(llm.router)
# api_router.include_router(mcp.router)
