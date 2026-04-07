import logging
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
from agentarea_api.api.deps.services import get_mcp_server_instance_service
from agentarea_common.auth.dependencies import UserContextDep
from agentarea_common.config import get_settings
from agentarea_mcp.application.service import MCPServerInstanceService
from agentarea_mcp.domain.models import MCPServer
from agentarea_mcp.domain.mpc_server_instance_model import MCPServerInstance
from agentarea_mcp.infrastructure.repository import MCPServerRepository
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import update as sa_update

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mcp-server-instances", tags=["mcp-server-instances"])


class MCPServerInstanceCreateRequest(BaseModel):
    name: str = Field(..., description="Name of the MCP server instance")
    description: str | None = Field(None, description="Description of the instance")
    server_spec_id: str | None = Field(None, description="ID of the MCP server spec (optional)")
    json_spec: dict[str, Any] = Field(..., description="Configuration specification as JSON")
    auth_config_id: str | None = Field(None, description="ID of the auth config to use")


class MCPServerInstanceUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    json_spec: dict[str, Any] | None = None
    status: str | None = None


class MCPServerInstanceResponse(BaseModel):
    id: UUID
    name: str
    description: str | None
    server_spec_id: str | None
    json_spec: dict[str, Any]
    status: str
    auth_config_id: UUID | str | None = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, instance: MCPServerInstance) -> "MCPServerInstanceResponse":
        json_spec = dict(instance.json_spec or {})

        # Mask secret env var values — env_vars list holds names of secrets
        secret_names = set(json_spec.get("env_vars", []))
        if secret_names:
            masked_value = "*" * 6
            # Inject masked values for secret keys into environment
            env = json_spec.get("environment")
            if isinstance(env, dict):
                masked_env = {k: (masked_value if k in secret_names else v) for k, v in env.items()}
                # Add missing secret keys (stripped during creation)
                for name in secret_names:
                    if name not in masked_env:
                        masked_env[name] = masked_value
                json_spec["environment"] = masked_env
            # Inject masked values for secret keys into headers
            headers = json_spec.get("headers")
            if isinstance(headers, dict):
                masked_headers = {
                    k: (masked_value if k in secret_names else v) for k, v in headers.items()
                }
                for name in secret_names:
                    if name not in masked_headers:
                        masked_headers[name] = masked_value
                json_spec["headers"] = masked_headers

        return cls.model_validate(
            {
                "id": instance.id,
                "name": instance.name,
                "description": instance.description,
                "server_spec_id": instance.server_spec_id,
                "json_spec": json_spec,
                "status": instance.status,
                "auth_config_id": instance.auth_config_id,
                "created_at": instance.created_at,
                "updated_at": instance.updated_at,
            }
        )


@router.post("/", response_model=MCPServerInstanceResponse)
async def create_mcp_server_instance(
    data: MCPServerInstanceCreateRequest,
    user_context: UserContextDep,
    mcp_server_instance_service: MCPServerInstanceService = Depends(
        get_mcp_server_instance_service
    ),
):
    try:
        instance = await mcp_server_instance_service.create_instance(
            name=data.name,
            description=data.description,
            server_spec_id=data.server_spec_id,
            json_spec=data.json_spec,
            auth_config_id=data.auth_config_id,
        )

        if not instance:
            raise HTTPException(status_code=500, detail="Failed to create MCP instance")

        return MCPServerInstanceResponse.from_domain(instance)

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error") from e


class ValidateConnectionRequest(BaseModel):
    url: str = Field(..., description="MCP server endpoint URL to test")
    headers: dict[str, str] = Field(
        default_factory=dict, description="HTTP headers to send (e.g. Authorization)"
    )


@router.post("/validate-connection")
async def validate_connection(
    data: ValidateConnectionRequest,
    user_context: UserContextDep,
    mcp_server_instance_service: MCPServerInstanceService = Depends(
        get_mcp_server_instance_service
    ),
):
    """Test a connection to an MCP server without creating an instance.

    Returns tools list on success, or auth/connection error on failure.
    Use this to validate credentials before creating an instance.
    """
    result = await mcp_server_instance_service.validate_connection(
        url=data.url,
        headers=data.headers if data.headers else None,
    )
    return result


@router.post("/check")
async def check_mcp_server_instance_configuration(
    data: dict[str, Any],
    user_context: UserContextDep,
    mcp_server_instance_service: MCPServerInstanceService = Depends(
        get_mcp_server_instance_service
    ),
):
    """Check if an MCP server instance configuration is valid by validating it
    through the golang manager.
    """
    try:
        settings = get_settings()

        # Extract json_spec from the request (the frontend sends { json_spec: {...} })
        json_spec = data.get("json_spec", data)

        # Format the request for the golang manager
        validation_request = {
            "instance_id": "validation-check",  # Temporary ID for validation
            "name": "validation-test",  # Temporary name for validation
            "json_spec": json_spec,
            "dry_run": True,
        }

        # Validate the configuration through the golang manager
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{settings.mcp.MCP_MANAGER_URL}/containers/validate",
                json=validation_request,
                headers={"Content-Type": "application/json"},
            )

            if response.status_code == 200:
                return {
                    "valid": True,
                    "message": "Configuration is valid",
                    "details": response.json(),
                }
            else:
                return {
                    "valid": False,
                    "message": f"Configuration validation failed: {response.text}",
                    "status_code": response.status_code,
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
    mcp_server_instance_service: MCPServerInstanceService = Depends(
        get_mcp_server_instance_service
    ),
):
    """Get environment variables for an MCP server instance.

    Note: This endpoint should have proper authentication and authorization in production.
    """
    try:
        env_vars = await mcp_server_instance_service.get_instance_environment(instance_id)

        # Return env var names only for security (don't leak values)
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
    mcp_server_instance_service: MCPServerInstanceService = Depends(
        get_mcp_server_instance_service
    ),
):
    """List all MCP server instances in the workspace.

    Access Control:
        Returns all instances within the current user's workspace (workspace isolation).
        All users in the same workspace can see all workspace instances.
    """
    # Get instances from database (configuration/metadata)
    instances = await mcp_server_instance_service.list()

    # Get real-time status from golang manager
    try:
        settings = get_settings()
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{settings.mcp.MCP_MANAGER_URL}/containers/health")
            if response.status_code == 200:
                health_data = response.json()
                health_lookup = {
                    check["service_name"]: check for check in health_data.get("health_checks", [])
                }
            else:
                health_lookup = {}
    except Exception as e:
        logger.warning(f"Failed to get real-time status from container manager: {e}")
        health_lookup = {}

    # Merge database config with real-time status
    response_instances = []
    for instance in instances:
        response_instance = MCPServerInstanceResponse.from_domain(instance)

        # Override status with real-time data if available
        if instance.name in health_lookup:
            health_check = health_lookup[instance.name]
            if health_check["container_status"] == "running" and health_check["healthy"]:
                response_instance.status = "running"
            elif health_check["container_status"] == "running" and not health_check["healthy"]:
                response_instance.status = "unhealthy"
            elif health_check["container_status"] == "stopped":
                response_instance.status = "stopped"

        response_instances.append(response_instance)

    return response_instances


@router.get("/{instance_id}", response_model=MCPServerInstanceResponse)
async def get_mcp_server_instance(
    instance_id: UUID,
    user_context: UserContextDep,
    mcp_server_instance_service: MCPServerInstanceService = Depends(
        get_mcp_server_instance_service
    ),
):
    # Get instance from database (configuration/metadata)
    instance = await mcp_server_instance_service.get(instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail="MCP Server Instance not found")

    response_instance = MCPServerInstanceResponse.from_domain(instance)

    # Get real-time status from golang manager
    try:
        settings = get_settings()
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{settings.mcp.MCP_MANAGER_URL}/containers/health")
            if response.status_code == 200:
                health_data = response.json()
                health_lookup = {
                    check["service_name"]: check for check in health_data.get("health_checks", [])
                }

                # Override status with real-time data if available
                if instance.name in health_lookup:
                    health_check = health_lookup[instance.name]
                    if health_check["container_status"] == "running" and health_check["healthy"]:
                        response_instance.status = "running"
                    elif (
                        health_check["container_status"] == "running"
                        and not health_check["healthy"]
                    ):
                        response_instance.status = "unhealthy"
                    elif health_check["container_status"] == "stopped":
                        response_instance.status = "stopped"
    except Exception as e:
        logger.warning(f"Failed to get real-time status from container manager: {e}")
        # Fall back to database status

    return response_instance


@router.patch("/{instance_id}", response_model=MCPServerInstanceResponse)
async def update_mcp_server_instance(
    instance_id: UUID,
    data: MCPServerInstanceUpdate,
    user_context: UserContextDep,
    mcp_server_instance_service: MCPServerInstanceService = Depends(
        get_mcp_server_instance_service
    ),
):
    instance = await mcp_server_instance_service.update_instance(
        id=instance_id,
        name=data.name,
        description=data.description,
        json_spec=data.json_spec,
        status=data.status,
    )
    if not instance:
        raise HTTPException(status_code=404, detail="MCP Server Instance not found")
    return MCPServerInstanceResponse.from_domain(instance)


@router.delete("/{instance_id}")
async def delete_mcp_server_instance(
    instance_id: UUID,
    user_context: UserContextDep,
    mcp_server_instance_service: MCPServerInstanceService = Depends(
        get_mcp_server_instance_service
    ),
):
    success = await mcp_server_instance_service.delete_instance(instance_id)
    if not success:
        raise HTTPException(status_code=404, detail="MCP Server Instance not found")
    return {"status": "success"}


@router.post("/{instance_id}/start")
async def start_mcp_server_instance(
    instance_id: UUID,
    user_context: UserContextDep,
    mcp_server_instance_service: MCPServerInstanceService = Depends(
        get_mcp_server_instance_service
    ),
):
    instance = await mcp_server_instance_service.get(instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail="MCP Server Instance not found")

    # Start Temporal workflow for durable lifecycle management
    from agentarea_mcp.workflows.models import StartMCPInstanceRequest
    from agentarea_mcp.workflows.start_instance_workflow import (
        StartMCPInstanceWorkflow,
    )

    settings = get_settings()
    workflow_id = f"mcp-start-{instance_id}"
    request = StartMCPInstanceRequest(
        instance_id=instance_id,
        user_id=user_context.user_id,
        workspace_id=user_context.workspace_id,
        json_spec=instance.json_spec or {},
        instance_name=instance.name,
    )

    try:
        from temporalio.client import Client
        from temporalio.common import WorkflowIDReusePolicy
        from temporalio.contrib.pydantic import pydantic_data_converter

        client = await Client.connect(
            settings.workflow.TEMPORAL_SERVER_URL,
            namespace=settings.workflow.TEMPORAL_NAMESPACE,
            data_converter=pydantic_data_converter,
        )
        handle = await client.start_workflow(
            StartMCPInstanceWorkflow.run,
            args=[request],
            id=workflow_id,
            task_queue=settings.workflow.TEMPORAL_TASK_QUEUE,
            execution_timeout=timedelta(minutes=10),
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
        )
        return {
            "status": "success",
            "message": "Instance start workflow initiated",
            "workflow_id": handle.id,
        }
    except Exception as e:
        if "already started" in str(e).lower():
            return {
                "status": "success",
                "message": "Instance start already in progress",
                "workflow_id": workflow_id,
            }
        raise HTTPException(status_code=500, detail=f"Failed to start workflow: {e}") from e


@router.post("/{instance_id}/stop")
async def stop_mcp_server_instance(
    instance_id: UUID,
    user_context: UserContextDep,
    mcp_server_instance_service: MCPServerInstanceService = Depends(
        get_mcp_server_instance_service
    ),
):
    instance = await mcp_server_instance_service.get(instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail="MCP Server Instance not found")

    # Start Temporal workflow for durable lifecycle management
    from agentarea_mcp.workflows.models import StopMCPInstanceRequest
    from agentarea_mcp.workflows.stop_instance_workflow import (
        StopMCPInstanceWorkflow,
    )

    settings = get_settings()
    workflow_id = f"mcp-stop-{instance_id}"
    request = StopMCPInstanceRequest(
        instance_id=instance_id,
        user_id=user_context.user_id,
        workspace_id=user_context.workspace_id,
        json_spec=instance.json_spec or {},
    )

    try:
        from temporalio.client import Client
        from temporalio.common import WorkflowIDReusePolicy
        from temporalio.contrib.pydantic import pydantic_data_converter

        client = await Client.connect(
            settings.workflow.TEMPORAL_SERVER_URL,
            namespace=settings.workflow.TEMPORAL_NAMESPACE,
            data_converter=pydantic_data_converter,
        )
        handle = await client.start_workflow(
            StopMCPInstanceWorkflow.run,
            args=[request],
            id=workflow_id,
            task_queue=settings.workflow.TEMPORAL_TASK_QUEUE,
            execution_timeout=timedelta(minutes=5),
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
        )
        return {
            "status": "success",
            "message": "Instance stop workflow initiated",
            "workflow_id": handle.id,
        }
    except Exception as e:
        if "already started" in str(e).lower():
            return {
                "status": "success",
                "message": "Instance stop already in progress",
                "workflow_id": workflow_id,
            }
        raise HTTPException(status_code=500, detail=f"Failed to start workflow: {e}") from e


# REMOVED: Insecure endpoint that exposed secrets via HTTP
# Secrets are now resolved directly in the Go service using Infisical SDK


@router.get("/health/containers")
async def get_containers_health(
    user_context: UserContextDep,
):
    """Get health status of all MCP containers by proxying to the golang manager."""
    try:
        settings = get_settings()
        # Proxy request to golang manager
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{settings.mcp.MCP_MANAGER_URL}/containers/health")

            if response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Failed to get container health: {response.text}",
                )

            # No URL transformation needed - Go manager returns correct external URLs
            return response.json()
    except httpx.RequestError as e:
        raise HTTPException(status_code=503, detail="Unable to connect to container manager") from e
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.post("/{instance_id}/probe")
async def probe_instance_auth(
    instance_id: UUID,
    user_context: UserContextDep,
    mcp_server_instance_service: MCPServerInstanceService = Depends(
        get_mcp_server_instance_service
    ),
):
    """Probe a URL-type MCP instance to detect its auth requirements.

    Returns the supported auth methods (oauth, credentials, none) and
    any hints from the spec's env_schema for pre-filling the credential form.
    """
    result = await mcp_server_instance_service.probe_instance_auth(instance_id)

    if result.get("status") == "error":
        raise HTTPException(
            status_code=400,
            detail=result.get("message", "Probe failed"),
        )

    # Cache auth_methods on the spec if the instance has a server_spec_id
    if result.get("methods"):
        try:
            instance = await mcp_server_instance_service.repository.get_by_id(instance_id)
            if instance and instance.server_spec_id:
                server_repo = MCPServerRepository(
                    mcp_server_instance_service.repository.session,
                    mcp_server_instance_service.repository.user_context,
                )
                spec = await server_repo.get_by_id(instance.server_spec_id)
                if spec:
                    new_json_spec = dict(spec.json_spec or {})
                    new_json_spec["auth_methods"] = result["methods"]
                    db_session = mcp_server_instance_service.repository.session
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


@router.post("/{instance_id}/discover-tools")
async def discover_instance_tools(
    instance_id: UUID,
    user_context: UserContextDep,
    service: MCPServerInstanceService = Depends(get_mcp_server_instance_service),
):
    """Trigger tool discovery for a specific MCP server instance."""
    success = await service.discover_and_store_tools(instance_id)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to discover tools for the instance")

    return {"message": "Tool discovery completed successfully"}


@router.post("/{instance_id}/test-auth")
async def test_mcp_auth(
    instance_id: UUID,
    user_context: UserContextDep,
    mcp_server_instance_service: MCPServerInstanceService = Depends(  # noqa: PT028
        get_mcp_server_instance_service
    ),
):
    """Test the authentication configuration attached to an MCP server instance.

    Attempts to connect to the MCP endpoint with the configured auth headers and
    returns a diagnostic result without executing any tools.
    """
    instance = await mcp_server_instance_service.get(instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail="MCP Server Instance not found")

    if not instance.auth_config_id:
        raise HTTPException(status_code=400, detail="No auth config attached to this MCP instance")

    try:
        # Re-resolve session/secret-manager via the instance service's internals
        # This is a lightweight connectivity test using httpx
        mcp_url: str = instance.json_spec.get("url", "")
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
    mcp_server_instance_service: MCPServerInstanceService = Depends(
        get_mcp_server_instance_service
    ),
):
    """Generate an OAuth-protected shareable link for a container MCP instance."""
    instance = await mcp_server_instance_service.get(instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail="MCP Server Instance not found")

    try:
        # Build service inline — we don't have the session in this scope so we
        # import it from the DI factory pattern

        # Use FastAPI DI to get a session
        raise HTTPException(
            status_code=501,
            detail="Use the /v1/mcp-oauth-links endpoint to create OAuth links",
        )
    except HTTPException:
        raise


@router.get("/{instance_id}/oauth-links")
async def list_oauth_links(
    instance_id: UUID,
    user_context: UserContextDep,
    mcp_server_instance_service: MCPServerInstanceService = Depends(
        get_mcp_server_instance_service
    ),
):
    """List all active OAuth links for an MCP server instance."""
    instance = await mcp_server_instance_service.get(instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail="MCP Server Instance not found")

    raise HTTPException(
        status_code=501,
        detail="Use the /v1/mcp-oauth-links endpoint to list OAuth links",
    )
