"""Mount compound MCP proxies as Streamable HTTP endpoints.

Each compound MCP gets its own `/mcp/{slug}/` path — clients connect to it
like any other MCP server. Internally it fans out to member instances.
"""

import logging
from uuid import UUID

from agentarea_api.api.deps.services import DatabaseSessionDep
from agentarea_common.auth.dependencies import UserContextDep
from agentarea_mcp.application.compound_proxy import build_compound_proxy
from agentarea_mcp.application.compound_service import CompoundMCPService
from agentarea_mcp.infrastructure.auth_repository import CompoundMCPRepository
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["compound-mcp-proxy"])


@router.get("/v1/compound-mcps/{compound_id}/endpoint")
async def get_compound_endpoint_info(
    compound_id: UUID,
    db_session: DatabaseSessionDep,
    user_context: UserContextDep,
):
    """Return the MCP endpoint URL for a compound MCP."""
    repo = CompoundMCPRepository(db_session, user_context)
    service = CompoundMCPService(repo)
    compound = await service.get(compound_id)
    if compound is None:
        raise HTTPException(status_code=404, detail="Compound MCP not found")

    # Slug: use the compound name, slugified
    slug = compound.name.lower().replace(" ", "-").replace("_", "-")
    return JSONResponse(
        {
            "compound_id": str(compound_id),
            "name": compound.name,
            "slug": slug,
            "endpoint_url": f"/mcp/compound-{slug}",
            "sse_url": f"/mcp/compound-{slug}/sse",
        }
    )


@router.post("/v1/compound-mcps/{compound_id}/start")
async def start_compound_proxy(
    compound_id: UUID,
    db_session: DatabaseSessionDep,
    user_context: UserContextDep,
):
    """Build and register a compound MCP proxy server.

    This discovers tools from all member instances and makes the compound
    available as an MCP endpoint.  Call this after adding/removing members.
    """
    try:
        proxy = await build_compound_proxy(compound_id, db_session, user_context)
        server = await proxy.build_server()

        # Store in the registry so the mount middleware can serve it
        from agentarea_api.api.v1.compound_mcp_registry import registry

        slug = proxy.name.lower().replace(" ", "-").replace("_", "-")
        key = f"compound-{slug}"
        registry[key] = proxy.get_asgi_app()

        logger.info("Compound MCP proxy started: %s at /mcp/%s", proxy.name, key)

        return JSONResponse(
            {
                "status": "started",
                "compound_id": str(compound_id),
                "name": proxy.name,
                "endpoint_url": f"/mcp/{key}",
                "tool_count": len(server._tool_manager._tools)
                if hasattr(server, "_tool_manager")
                else 0,
            }
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to start compound proxy for %s", compound_id)
        raise HTTPException(
            status_code=500, detail=f"Failed to start proxy: {exc}"
        ) from exc


@router.post("/v1/compound-mcps/{compound_id}/stop")
async def stop_compound_proxy(
    compound_id: UUID,
    db_session: DatabaseSessionDep,
    user_context: UserContextDep,
):
    """Stop a running compound MCP proxy."""
    repo = CompoundMCPRepository(db_session, user_context)
    service = CompoundMCPService(repo)
    compound = await service.get(compound_id)
    if compound is None:
        raise HTTPException(status_code=404, detail="Compound MCP not found")

    from agentarea_api.api.v1.compound_mcp_registry import registry

    slug = compound.name.lower().replace(" ", "-").replace("_", "-")
    key = f"compound-{slug}"

    if key in registry:
        del registry[key]
        logger.info("Compound MCP proxy stopped: %s", key)
        return JSONResponse({"status": "stopped", "compound_id": str(compound_id)})

    return JSONResponse({"status": "not_running", "compound_id": str(compound_id)})


@router.post("/v1/mcp-server-instances/{instance_id}/start-bundle")
async def start_bundle_proxy(
    instance_id: UUID,
    db_session: DatabaseSessionDep,
    user_context: UserContextDep,
):
    """Build and register a bundle MCP proxy server."""
    from agentarea_mcp.application.compound_proxy import build_bundle_proxy
    from agentarea_api.api.v1.compound_mcp_registry import registry

    try:
        proxy = await build_bundle_proxy(instance_id, db_session, user_context)
        await proxy.build_server()

        key = f"bundle-{instance_id}"
        registry[key] = proxy.get_asgi_app()
        logger.info("Bundle proxy started: %s at /bundle-mcp/%s", proxy.name, instance_id)

        return JSONResponse({
            "status": "started",
            "instance_id": str(instance_id),
            "name": proxy.name,
            "endpoint_url": f"/bundle-mcp/{instance_id}",
        })
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to start bundle proxy for %s", instance_id)
        raise HTTPException(status_code=500, detail=f"Failed to start proxy: {exc}") from exc


@router.post("/v1/mcp-server-instances/{instance_id}/stop-bundle")
async def stop_bundle_proxy(
    instance_id: UUID,
    db_session: DatabaseSessionDep,
    user_context: UserContextDep,
):
    """Stop a running bundle MCP proxy."""
    from agentarea_api.api.v1.compound_mcp_registry import registry

    key = f"bundle-{instance_id}"
    if key in registry:
        del registry[key]
        logger.info("Bundle proxy stopped: bundle-%s", instance_id)
        return JSONResponse({"status": "stopped", "instance_id": str(instance_id)})

    return JSONResponse({"status": "not_running", "instance_id": str(instance_id)})
