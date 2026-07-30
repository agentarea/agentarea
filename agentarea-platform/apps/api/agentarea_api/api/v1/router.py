"""API v1 router with protected and public endpoint separation.

This module splits endpoints into protected (require authentication) and
public (no authentication required) routers, following FastAPI best practices.
"""

from agentarea_common.auth.dependencies import get_user_context
from fastapi import APIRouter, Depends

# Import core API modules
from . import (
    access_control,
    agent_overview,
    agents,
    agents_a2a,
    agents_tasks,
    agents_well_known,
    api_keys,
    audit,
    bundles,
    clients,
    dashboard,
    files,
    governance,
    inbox,
    mcp_auth_configs,
    mcp_oauth_connect,
    mcp_oauth_links,
    mcp_proxy,
    mcp_server_instances,
    mcp_servers_specifications,
    model_instances,
    model_specs,
    network,
    openapi_connections,
    policies,
    projects,
    provider_configs,
    provider_specs,
    registries,
    sandboxes,
    skill_collections,
    skills,
    triggers,
    wallet,
    workspace_config,
    workspace_invitations,
    workspaces,
)

# ============================================================================
# PUBLIC ROUTER - No authentication required
# ============================================================================
public_v1_router = APIRouter(prefix="/v1", tags=["public"])

# MCP OAuth callback (public — user is mid-redirect from external AS)
public_v1_router.include_router(mcp_oauth_connect.public_router)

# Trigger execute endpoint (public — called by internal Go event-service)
public_v1_router.include_router(triggers.public_router)

# A2A Agent Card discovery is public by protocol; execution RPC remains protected below.
public_v1_router.include_router(agents_well_known.router, prefix="/agents/{agent_id}")

# Webhook receiver is mounted directly on app (not under /v1) to avoid auth conflicts
# See main.py: app.include_router(webhooks.router, prefix="/webhooks", tags=["webhooks"])

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
protected_v1_router.include_router(wallet.router)
protected_v1_router.include_router(agents_tasks.router)
protected_v1_router.include_router(agents_tasks.global_tasks_router)

# A2A protocol routers - Have their own auth system
# These are protected by A2A-specific dependencies (see a2a_auth.py)
protected_v1_router.include_router(agents_a2a.router, prefix="/agents/{agent_id}")

# MCP server management - PROTECTED
protected_v1_router.include_router(mcp_servers_specifications.router)
protected_v1_router.include_router(mcp_server_instances.router)

# LLM architecture routers (4-entity system) - PROTECTED
protected_v1_router.include_router(provider_specs.router)
protected_v1_router.include_router(provider_configs.router)
protected_v1_router.include_router(model_specs.router)
protected_v1_router.include_router(model_instances.router)

# Webhook management - Public (moved to public_v1_router above)

# Triggers management - PROTECTED
protected_v1_router.include_router(triggers.router)

# Workspace configuration import/export - PROTECTED
protected_v1_router.include_router(workspace_config.router)

# Workspace invitations + memberships - PROTECTED
protected_v1_router.include_router(workspace_invitations.router)
protected_v1_router.include_router(workspaces.router)

# Skills management - PROTECTED
protected_v1_router.include_router(skills.router)

# Bundle import (analyze + install) - PROTECTED
protected_v1_router.include_router(bundles.router)

# Skill collections (grouping for access-control fan-out) - PROTECTED
protected_v1_router.include_router(skill_collections.router)

protected_v1_router.include_router(access_control.router, prefix="/access-control")

# MCP Auth Configs - PROTECTED
protected_v1_router.include_router(mcp_auth_configs.router)

# MCP OAuth Links management - PROTECTED
protected_v1_router.include_router(mcp_oauth_links.router)

# MCP OAuth Connect (client-side) - PROTECTED for /authorize, callback is public
protected_v1_router.include_router(mcp_oauth_connect.router)

# MCP API Keys management - PROTECTED
protected_v1_router.include_router(api_keys.router)

# MCP per-instance reverse proxy (Streamable HTTP) - PROTECTED
protected_v1_router.include_router(mcp_proxy.router)

# Registries (MCP catalog) - PROTECTED
protected_v1_router.include_router(registries.router)

# Bundle proxy start/stop is part of mcp_server_instances router (above)

# OpenAPI connections - PROTECTED
protected_v1_router.include_router(openapi_connections.router)

# Network topology - PROTECTED
protected_v1_router.include_router(network.router)

# Projects - PROTECTED
protected_v1_router.include_router(projects.router)
protected_v1_router.include_router(clients.router)

# Audit logs - PROTECTED
protected_v1_router.include_router(audit.router)

# Dashboard + workspace settings - PROTECTED
protected_v1_router.include_router(dashboard.router)
protected_v1_router.include_router(agent_overview.router)

# Governance effective-policy preview + task snapshots - PROTECTED
protected_v1_router.include_router(governance.router)

# Unified policy rules (source of truth CRUD) - PROTECTED
protected_v1_router.include_router(policies.router)

# Inbox - PROTECTED
protected_v1_router.include_router(inbox.router)

# Workspace files (read-only listing of S3 objects under workspaces/{workspace_id}/) - PROTECTED
protected_v1_router.include_router(files.router)

# Live sandbox inventory - PROTECTED and scoped by UserContext.
protected_v1_router.include_router(sandboxes.router)
