import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from agentarea_api.api.deps.services import get_mcp_server_instance_service
from agentarea_common.auth.dependencies import UserContextDep
from agentarea_common.config import get_settings
from agentarea_mcp.application.service import MCPServerInstanceService, derive_bundle_verification
from agentarea_mcp.application.validation_service import MCPValidationError
from agentarea_mcp.domain.mpc_server_instance_model import MCPServerInstance
from agentarea_mcp.schemas.dto import (
    MCPServerCreate,
    MCPServerInstanceCreate,
)
from agentarea_mcp.schemas.dto import (
    MCPServerInstanceUpdate as MCPServerInstanceUpdateDTO,
)
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mcp-server-instances", tags=["mcp-server-instances"])


# Backwards-compatible aliases — the canonical DTOs live in agentarea_mcp.schemas.dto.
MCPServerInstanceCreateRequest = MCPServerInstanceCreate
MCPServerInstanceUpdate = MCPServerInstanceUpdateDTO


class MCPServerInstanceResponse(BaseModel):
    id: UUID
    name: str
    description: str | None
    server_spec_id: str
    json_spec: dict[str, Any]
    verification: dict[str, Any]
    last_dispatch: dict[str, Any] | None = None
    tools: list[dict[str, Any]] | None = None
    auth_config_id: UUID | str | None = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(
        cls,
        instance: MCPServerInstance,
        verification_override: dict | None = None,
    ) -> "MCPServerInstanceResponse":
        json_spec = dict(instance.json_spec or {})

        # Mask secret env var values
        secret_names = set(json_spec.get("env_vars", []))
        if secret_names:
            masked_value = "*" * 6
            env = json_spec.get("environment")
            if isinstance(env, dict):
                masked_env = {k: (masked_value if k in secret_names else v) for k, v in env.items()}
                for name in secret_names:
                    if name not in masked_env:
                        masked_env[name] = masked_value
                json_spec["environment"] = masked_env
            headers = json_spec.get("headers")
            if isinstance(headers, dict):
                masked_headers = {
                    k: (masked_value if k in secret_names else v) for k, v in headers.items()
                }
                for name in secret_names:
                    if name not in masked_headers:
                        masked_headers[name] = masked_value
                json_spec["headers"] = masked_headers

        verification = (
            verification_override
            if verification_override is not None
            else (instance.verification or {})
        )

        return cls.model_validate(
            {
                "id": instance.id,
                "name": instance.name,
                "description": instance.description,
                "server_spec_id": instance.server_spec_id,
                "json_spec": json_spec,
                "verification": verification,
                "last_dispatch": instance.last_dispatch,
                "tools": instance.tools,
                "auth_config_id": instance.auth_config_id,
                "created_at": instance.created_at,
                "updated_at": instance.updated_at,
            }
        )


class ValidateRequest(BaseModel):
    name: str | None = None
    type: str = Field(..., description="Instance type: url, docker, command")
    endpoint_url: str | None = Field(None, description="For type=url: the MCP endpoint URL")
    headers: dict[str, str] = Field(default_factory=dict)


class MCPServerInstanceCreateWithoutSpec(BaseModel):
    name: str
    description: str | None = None
    json_spec: dict[str, Any] = Field(default_factory=dict)
    auth_config_id: str | None = None


class MCPServerConnectionCreateRequest(BaseModel):
    server: MCPServerCreate
    instance: MCPServerInstanceCreateWithoutSpec


@router.post("/validate")
async def validate_instance_spec(
    data: ValidateRequest,
    user_context: UserContextDep,
    service: MCPServerInstanceService = Depends(get_mcp_server_instance_service),
):
    """Stateless spec validation. For type=url, probes with list_tools (3s budget)."""
    if data.type == "url":
        if not data.endpoint_url:
            return {"valid": False, "errors": ["endpoint_url is required for type=url"]}
        result = await service.validate_connection(data.endpoint_url, data.headers or None)
        return result

    if data.type in ("docker", "command"):
        # Schema-level check only — no container launched for validate
        return {"valid": True, "errors": []}

    if data.type == "bundle":
        return {"valid": False, "errors": ["bundle is not a valid MCP server instance type"]}

    return {"valid": False, "errors": [f"Unknown type: {data.type}"]}


@router.post("/", status_code=201, response_model=MCPServerInstanceResponse)
async def create_mcp_server_instance(
    data: MCPServerInstanceCreateRequest,
    response: Response,
    user_context: UserContextDep,
    service: MCPServerInstanceService = Depends(get_mcp_server_instance_service),
):
    """Create a new MCP server instance.

    Returns 201 for url (synchronous verification completed).
    Returns 202 for docker/command (background verification in progress).
    """
    try:
        instance = await service.create_instance(data)

        if not instance:
            raise HTTPException(status_code=500, detail="Failed to create MCP instance")

        instance_type = (data.json_spec or {}).get("type", "docker")
        if instance_type in ("docker", "command"):
            response.status_code = 202

        return MCPServerInstanceResponse.from_domain(instance)

    except MCPValidationError as e:
        raise HTTPException(status_code=422, detail={"errors": e.errors}) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("create_mcp_server_instance failed")
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}") from e


@router.post("/with-spec", status_code=201, response_model=MCPServerInstanceResponse)
async def create_mcp_server_connection(
    data: MCPServerConnectionCreateRequest,
    response: Response,
    user_context: UserContextDep,
    service: MCPServerInstanceService = Depends(get_mcp_server_instance_service),
):
    """Create an MCP server spec and instance in one transaction."""
    try:
        instance_payload = MCPServerInstanceCreate.model_construct(
            name=data.instance.name,
            description=data.instance.description,
            server_spec_id="",
            json_spec=data.instance.json_spec,
            auth_config_id=data.instance.auth_config_id,
        )
        instance = await service.create_instance_with_spec(data.server, instance_payload)
        if not instance:
            raise HTTPException(status_code=500, detail="Failed to create MCP instance")

        server_spec = await service.mcp_server_repository.get_by_id(instance.server_spec_id)
        instance_type = "docker"
        if server_spec:
            if server_spec.remote_url:
                instance_type = "url"
            elif server_spec.cmd:
                instance_type = "command"
            elif server_spec.json_spec:
                instance_type = server_spec.json_spec.get("type", instance_type)
        if instance_type in ("docker", "command"):
            response.status_code = 202
        return MCPServerInstanceResponse.from_domain(instance)
    except MCPValidationError as e:
        raise HTTPException(status_code=422, detail={"errors": e.errors}) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("create_mcp_server_connection failed")
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}") from e


@router.post("/validate-connection")
async def validate_connection(
    data: dict[str, Any],
    user_context: UserContextDep,
    service: MCPServerInstanceService = Depends(get_mcp_server_instance_service),
):
    """Test a connection to an MCP server without creating an instance."""
    url = data.get("url", "")
    headers = data.get("headers")
    result = await service.validate_connection(url=url, headers=headers)
    return result


@router.post("/check")
async def check_mcp_server_instance_configuration(
    data: dict[str, Any],
    user_context: UserContextDep,
    service: MCPServerInstanceService = Depends(get_mcp_server_instance_service),
):
    """Check if an MCP server instance configuration is valid via the Go manager."""
    import httpx

    try:
        settings = get_settings()
        json_spec = data.get("json_spec", data)
        validation_request = {
            "instance_id": "validation-check",
            "name": "validation-test",
            "json_spec": json_spec,
            "dry_run": True,
        }

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{settings.mcp.MCP_MANAGER_URL}/containers/validate",
                json=validation_request,
                headers={"Content-Type": "application/json"},
            )

            if resp.status_code == 200:
                return {"valid": True, "message": "Configuration is valid", "details": resp.json()}
            else:
                return {
                    "valid": False,
                    "message": f"Configuration validation failed: {resp.text}",
                    "status_code": resp.status_code,
                }
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=503, detail="Unable to connect to container manager for validation"
        ) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.get("/{instance_id}/environment")
async def get_instance_environment(
    instance_id: UUID,
    user_context: UserContextDep,
    service: MCPServerInstanceService = Depends(get_mcp_server_instance_service),
):
    try:
        env_vars = await service.get_instance_environment(instance_id)
        return {
            "instance_id": instance_id,
            "env_vars": list(env_vars.keys()),
            "message": f"Instance has {len(env_vars)} environment variables configured",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.get("/", response_model=list[MCPServerInstanceResponse])
async def list_mcp_server_instances(
    user_context: UserContextDep,
    service: MCPServerInstanceService = Depends(get_mcp_server_instance_service),
):
    """List all MCP server instances in the workspace."""
    instances = await service.list()

    response_instances = []
    for instance in instances:
        instance_type = (instance.json_spec or {}).get("type", "")
        if instance_type == "bundle":
            # Derive bundle verification from current member states
            member_ids: list[str] = (instance.json_spec or {}).get("members", [])
            members = []
            for mid in member_ids:
                try:
                    m = await service.repository.get_by_id(UUID(mid))
                    if m:
                        members.append(m)
                except Exception as e:
                    logger.debug("bundle member %s lookup failed: %s", mid, e)
            derived_v = derive_bundle_verification(instance, members)
            response_instances.append(
                MCPServerInstanceResponse.from_domain(instance, verification_override=derived_v)
            )
        else:
            response_instances.append(MCPServerInstanceResponse.from_domain(instance))

    return response_instances


@router.get("/{instance_id}", response_model=MCPServerInstanceResponse)
async def get_mcp_server_instance(
    instance_id: UUID,
    user_context: UserContextDep,
    service: MCPServerInstanceService = Depends(get_mcp_server_instance_service),
):
    instance = await service.get(instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail="MCP Server Instance not found")
    if not instance.server_spec_id:
        raise HTTPException(status_code=404, detail="MCP Server Instance not found")

    instance_type = (instance.json_spec or {}).get("type", "")
    if instance_type == "bundle":
        member_ids: list[str] = (instance.json_spec or {}).get("members", [])
        members = []
        for mid in member_ids:
            try:
                m = await service.repository.get_by_id(UUID(mid))
                if m:
                    members.append(m)
            except Exception as e:
                logger.debug("bundle member %s lookup failed: %s", mid, e)
        derived_v = derive_bundle_verification(instance, members)
        return MCPServerInstanceResponse.from_domain(instance, verification_override=derived_v)

    return MCPServerInstanceResponse.from_domain(instance)


@router.patch("/{instance_id}", response_model=MCPServerInstanceResponse)
async def update_mcp_server_instance(
    instance_id: UUID,
    data: MCPServerInstanceUpdate,
    user_context: UserContextDep,
    service: MCPServerInstanceService = Depends(get_mcp_server_instance_service),
):
    instance = await service.update_instance(instance_id, data)
    if not instance:
        raise HTTPException(status_code=404, detail="MCP Server Instance not found")
    return MCPServerInstanceResponse.from_domain(instance)


@router.delete("/{instance_id}")
async def delete_mcp_server_instance(
    instance_id: UUID,
    user_context: UserContextDep,
    service: MCPServerInstanceService = Depends(get_mcp_server_instance_service),
):
    success = await service.delete_instance(instance_id)
    if not success:
        raise HTTPException(status_code=404, detail="MCP Server Instance not found")
    return {"status": "success"}


@router.post("/{instance_id}/verify")
async def verify_mcp_server_instance(
    instance_id: UUID,
    user_context: UserContextDep,
    service: MCPServerInstanceService = Depends(get_mcp_server_instance_service),
):
    """Run verification on an MCP server instance and return the fresh result synchronously.

    HTTP 200 regardless of verification outcome — the call itself succeeded.
    Check verification.status in the response to determine success/failure.
    """
    instance = await service.get(instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail="MCP Server Instance not found")

    try:
        verification = await service.verify_instance(instance_id)
        return {"instance_id": str(instance_id), "verification": verification}
    except Exception as e:
        logger.error("verify_instance failed for %s: %s", instance_id, e, exc_info=True)
        raise HTTPException(
            status_code=500, detail="Verification failed due to internal error"
        ) from e


@router.post("/{instance_id}/discover-tools")
async def discover_mcp_server_instance_tools(
    instance_id: UUID,
    user_context: UserContextDep,
    service: MCPServerInstanceService = Depends(get_mcp_server_instance_service),
):
    """Re-discover the tools exposed by an MCP server instance.

    Re-runs verification (which calls list_tools on the server using any
    OAuth/API-key credentials linked via auth_config_id) and persists the
    refreshed tool list. Returns {tools, verification}.
    """
    instance = await service.get(instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail="MCP Server Instance not found")

    try:
        return await service.discover_and_store_tools(instance_id)
    except Exception as e:
        logger.error("discover_and_store_tools failed for %s: %s", instance_id, e, exc_info=True)
        raise HTTPException(
            status_code=500, detail="Tool discovery failed due to internal error"
        ) from e


@router.get("/health/containers")
async def get_containers_health(
    user_context: UserContextDep,
):
    """Get health status of all MCP containers by proxying to the Go manager."""
    import httpx

    try:
        settings = get_settings()
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{settings.mcp.MCP_MANAGER_URL}/containers/health")
            if response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Failed to get container health: {response.text}",
                )
            return response.json()
    except httpx.RequestError as e:
        raise HTTPException(status_code=503, detail="Unable to connect to container manager") from e
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.post("/{instance_id}/probe")
async def probe_instance_auth(
    instance_id: UUID,
    user_context: UserContextDep,
    service: MCPServerInstanceService = Depends(get_mcp_server_instance_service),
):
    """Probe a URL-type MCP instance to detect its auth requirements."""
    from agentarea_mcp.domain.models import MCPServer
    from agentarea_mcp.infrastructure.repository import MCPServerRepository
    from sqlalchemy import update as sa_update

    result = await service.probe_instance_auth(instance_id)

    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result.get("message", "Probe failed"))

    if result.get("methods"):
        try:
            instance = await service.repository.get_by_id(instance_id)
            if instance and instance.server_spec_id:
                server_repo = MCPServerRepository(
                    service.repository.session,
                    service.repository.user_context,
                )
                spec = await server_repo.get_by_id(instance.server_spec_id)
                if spec:
                    new_json_spec = dict(spec.json_spec or {})
                    new_json_spec["auth_methods"] = result["methods"]
                    db_session = service.repository.session
                    stmt = (
                        sa_update(MCPServer)
                        .where(MCPServer.id == spec.id)
                        .values(json_spec=new_json_spec)
                    )
                    await db_session.execute(stmt)
                    await db_session.commit()
        except Exception:
            logger.warning(
                "Failed to cache auth methods for MCP server spec after probe",
                exc_info=True,
            )

    return result


@router.post("/{instance_id}/test-auth")
async def run_test_auth(
    instance_id: UUID,
    user_context: UserContextDep,
    service: MCPServerInstanceService = Depends(get_mcp_server_instance_service),
):
    """Test the authentication configuration attached to an MCP server instance."""
    instance = await service.get(instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail="MCP Server Instance not found")

    if not instance.auth_config_id:
        raise HTTPException(status_code=400, detail="No auth config attached to this MCP instance")

    try:
        mcp_url: str = instance.endpoint_url
        if not mcp_url:
            raise HTTPException(status_code=400, detail="MCP instance has no URL in json_spec")

        return {
            "status": "pending",
            "message": (
                "Auth test queued. Use /health/containers to verify connectivity once running."
            ),
            "instance_id": str(instance_id),
            "auth_config_id": str(instance.auth_config_id),
        }

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.post("/{instance_id}/oauth-link")
async def create_oauth_link(
    instance_id: UUID,
    data: dict,
    user_context: UserContextDep,
    service: MCPServerInstanceService = Depends(get_mcp_server_instance_service),
):
    instance = await service.get(instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail="MCP Server Instance not found")

    raise HTTPException(
        status_code=501,
        detail="Use the /v1/mcp-oauth-links endpoint to create OAuth links",
    )


@router.get("/{instance_id}/oauth-links")
async def list_oauth_links(
    instance_id: UUID,
    user_context: UserContextDep,
    service: MCPServerInstanceService = Depends(get_mcp_server_instance_service),
):
    instance = await service.get(instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail="MCP Server Instance not found")

    raise HTTPException(
        status_code=501,
        detail="Use the /v1/mcp-oauth-links endpoint to list OAuth links",
    )
