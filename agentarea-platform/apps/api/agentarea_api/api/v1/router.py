"""API v1 routers, split by how each route selects its workspace.

- ``public_v1_router``: no authentication (OAuth callbacks, agent discovery).
- ``principal_v1_router``: authenticated, but acts on no single workspace
  (listing/creating workspaces, previewing/accepting an invitation).
- ``workspace_v1_router``: everything that acts in a workspace, which the path
  names by slug: ``/v1/workspaces/{workspace}/...``.
- ``a2a_v1_router`` / ``mcp_proxy_v1_router``: addressed by an entity id whose
  URL is a published contract; they bind the entity's workspace instead.
"""

import re
from typing import Annotated

from agentarea_api.api.v1.a2a_auth import require_a2a_read_auth
from agentarea_api.api.v1.mcp_proxy import bind_mcp_instance_workspace
from agentarea_common.auth.dependencies import get_principal, get_user_context
from agentarea_common.workspaces.slug import (
    WORKSPACE_SLUG_COLUMN_LENGTH,
    WORKSPACE_SLUG_PATTERN,
)
from fastapi import APIRouter, Depends, Path
from fastapi.routing import APIRoute

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
    connection_oauth,
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
    principals,
    projects,
    provider_configs,
    provider_specs,
    registries,
    sandboxes,
    skill_collections,
    skills,
    triggers,
    usage,
    wallet,
    workspace_config,
    workspace_invitations,
    workspace_secrets,
    workspaces,
)

WORKSPACE_PREFIX = "/v1/workspaces/{workspace}"

# ============================================================================
# PUBLIC ROUTER - No authentication required
# ============================================================================
public_v1_router = APIRouter(prefix="/v1", tags=["public"])

# MCP OAuth callback (public — user is mid-redirect from external AS)
public_v1_router.include_router(mcp_oauth_connect.public_router)
public_v1_router.include_router(connection_oauth.public_router)

# A2A Agent Card discovery is public by protocol; execution RPC remains protected below.
public_v1_router.include_router(agents_well_known.router, prefix="/agents/{agent_id}")

# Webhook receiver is mounted directly on app (not under /v1) to avoid auth conflicts
# See main.py: app.include_router(webhooks.router, prefix="/webhooks", tags=["webhooks"])

# ============================================================================
# PRINCIPAL ROUTER - Authenticated, no workspace selected
# ============================================================================
principal_v1_router = APIRouter(
    prefix="/v1",
    dependencies=[Depends(get_principal)],
    tags=["protected"],
)

principal_v1_router.include_router(workspaces.router)
principal_v1_router.include_router(workspace_invitations.principal_router)


# ============================================================================
# WORKSPACE ROUTER - /v1/workspaces/{workspace}/..., the path selects the workspace
# ============================================================================
async def _workspace_path(
    workspace: Annotated[
        str,
        Path(
            pattern=WORKSPACE_SLUG_PATTERN,
            max_length=WORKSPACE_SLUG_COLUMN_LENGTH,
            description="Slug of the workspace the request acts in",
        ),
    ],
) -> None:
    """Declare and validate the ``{workspace}`` slug every workspace route carries."""


_WORKSPACE_SEGMENT = re.compile(r"^/v1/workspaces/\{workspace\}")


def workspace_route_unique_id(route: APIRoute) -> str:
    """FastAPI's default operation id, computed as if the workspace segment were absent.

    Keeps generated client names (``list_agents_v1_agents__get``) stable across
    the move of workspace selection from a header into the path.
    """
    path = _WORKSPACE_SEGMENT.sub("/v1", route.path_format)
    operation_id = re.sub(r"\W", "_", f"{route.name}{path}")
    return f"{operation_id}_{next(iter(route.methods)).lower()}"


workspace_v1_router = APIRouter(
    prefix=WORKSPACE_PREFIX,
    dependencies=[Depends(_workspace_path), Depends(get_user_context)],
    tags=["protected"],
    generate_unique_id_function=workspace_route_unique_id,
)

# Core agent operations
workspace_v1_router.include_router(agents.router)
workspace_v1_router.include_router(wallet.router)
workspace_v1_router.include_router(agents_tasks.router)
workspace_v1_router.include_router(agents_tasks.global_tasks_router)

# MCP server management
workspace_v1_router.include_router(mcp_servers_specifications.router)
workspace_v1_router.include_router(mcp_server_instances.router)

# LLM architecture routers (4-entity system)
workspace_v1_router.include_router(provider_specs.router)
workspace_v1_router.include_router(provider_configs.router)
workspace_v1_router.include_router(model_specs.router)
workspace_v1_router.include_router(model_instances.router)

# Triggers management
workspace_v1_router.include_router(triggers.router)

# Workspace configuration export
workspace_v1_router.include_router(workspace_config.router)

# Workspace invitations + memberships
workspace_v1_router.include_router(workspace_invitations.router)

# Principal (id -> who it is) resolution
workspace_v1_router.include_router(principals.router)

# Skills management
workspace_v1_router.include_router(skills.router)

# Bundle import (analyze + install)
workspace_v1_router.include_router(bundles.router)

# Skill collections (grouping for access-control fan-out)
workspace_v1_router.include_router(skill_collections.router)

workspace_v1_router.include_router(access_control.router, prefix="/access-control")

# MCP Auth Configs
workspace_v1_router.include_router(mcp_auth_configs.router)

# MCP OAuth Links management
workspace_v1_router.include_router(mcp_oauth_links.router)

# MCP OAuth Connect (client-side) - /authorize and /preflight; callbacks are public
workspace_v1_router.include_router(mcp_oauth_connect.router)
workspace_v1_router.include_router(connection_oauth.router)

# MCP API Keys management
workspace_v1_router.include_router(api_keys.router)

# Workspace secrets. User-owned rows only; the secrets the platform mints for
# a connection are managed through that connection.
workspace_v1_router.include_router(workspace_secrets.router)

# Registries (MCP catalog). Workspace-scoped: the registry service builds the
# repositories installs land in, and writing the global catalog means acting
# in the platform workspace (require_platform_catalog_write).
workspace_v1_router.include_router(registries.router)

# OpenAPI connections
workspace_v1_router.include_router(openapi_connections.router)

# Network topology
workspace_v1_router.include_router(network.router)

# Projects
workspace_v1_router.include_router(projects.router)
workspace_v1_router.include_router(clients.router)

# Audit logs
workspace_v1_router.include_router(audit.router)
workspace_v1_router.include_router(usage.router)

# Dashboard + workspace settings
workspace_v1_router.include_router(dashboard.router)
workspace_v1_router.include_router(agent_overview.router)

# Governance effective-policy preview + task snapshots
workspace_v1_router.include_router(governance.router)

# Unified policy rules (source of truth CRUD)
workspace_v1_router.include_router(policies.router)

# Inbox
workspace_v1_router.include_router(inbox.router)

# Workspace files (read-only listing of S3 objects under workspaces/{workspace_id}/)
workspace_v1_router.include_router(files.router)

# Live sandbox inventory, scoped by UserContext.
workspace_v1_router.include_router(sandboxes.router)


# ============================================================================
# ID-BOUND ROUTERS - published URLs addressed by an entity id
# ============================================================================
# A2A: the agent is looked up across workspaces, the caller is authorized
# against the agent's workspace, and that workspace is bound for the request.
a2a_v1_router = APIRouter(
    prefix="/v1/agents/{agent_id}",
    dependencies=[Depends(require_a2a_read_auth)],
    tags=["protected"],
)
a2a_v1_router.include_router(agents_a2a.router)

# MCP per-instance reverse proxy (Streamable HTTP): binds the instance's workspace.
mcp_proxy_v1_router = APIRouter(
    prefix="/v1",
    dependencies=[Depends(bind_mcp_instance_workspace)],
    tags=["protected"],
)
mcp_proxy_v1_router.include_router(mcp_proxy.router)
