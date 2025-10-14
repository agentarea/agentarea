"""API v1 router with protected and public endpoint separation.

This module splits endpoints into protected (require authentication) and
public (no authentication required) routers, following FastAPI best practices.
"""

from agentarea_common.auth.dependencies import get_user_context
from fastapi import APIRouter, Depends

# Import core API modules
from . import (
    agents,
    agents_a2a,
    agents_tasks,
    agents_well_known,
    mcp_server_instances,
    mcp_servers_specifications,
    model_instances,
    model_specs,
    provider_configs,
    provider_specs,
    triggers,
    webhooks,
)

# ============================================================================
# PUBLIC ROUTER - No authentication required
# ============================================================================
public_v1_router = APIRouter(prefix="/v1", tags=["public"])

# No public endpoints currently - all endpoints require authentication via middleware

# ============================================================================
# PROTECTED ROUTER - Authentication required for ALL endpoints
# ============================================================================
protected_v1_router = APIRouter(
    prefix="/v1",
    dependencies=[Depends(get_user_context)],  # Require authentication
    tags=["protected"],
)

# Core agent operations - PROTECTED
protected_v1_router.include_router(agents.router)
protected_v1_router.include_router(agents_tasks.router)
protected_v1_router.include_router(agents_tasks.global_tasks_router)

# A2A protocol routers - Have their own auth system
# These are protected by A2A-specific dependencies (see a2a_auth.py)
protected_v1_router.include_router(agents_a2a.router, prefix="/agents/{agent_id}")
protected_v1_router.include_router(agents_well_known.router, prefix="/agents/{agent_id}")

# MCP server management - PROTECTED
protected_v1_router.include_router(mcp_servers_specifications.router)
protected_v1_router.include_router(mcp_server_instances.router)

# LLM architecture routers (4-entity system) - PROTECTED
protected_v1_router.include_router(provider_specs.router)
protected_v1_router.include_router(provider_configs.router)
protected_v1_router.include_router(model_specs.router)
protected_v1_router.include_router(model_instances.router)

# Webhook management - PROTECTED
protected_v1_router.include_router(webhooks.router)

# Triggers management - PROTECTED
protected_v1_router.include_router(triggers.router)

# ============================================================================
# LEGACY: Keep old v1_router for backward compatibility during migration
# TODO: Remove after all references are updated to use protected/public routers
# ============================================================================
v1_router = protected_v1_router  # Default to protected for safety
