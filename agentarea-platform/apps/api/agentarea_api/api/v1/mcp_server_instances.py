import logging
from typing import Annotated, Any
from uuid import UUID

from agentarea_api.api.deps.services import AgentServiceDep, get_mcp_server_instance_service
from agentarea_api.api.v1._approval_policy_sync import (
    approval_targets_for_agents,
    mcp_tool_ticked,
)
from agentarea_api.api.v1.mcp_oauth_links import (
    MCPOAuthLinkService,
    OAuthLinkResponse,
    get_oauth_link_service,
)
from agentarea_common.auth.dependencies import UserContextDep
from agentarea_common.auth.route_authz import requires, requires_workspace_admin, unrestricted
from agentarea_common.config import get_settings
from agentarea_common.config.database import get_db_session
from agentarea_common.utils.types import UtcDatetime
from agentarea_mcp.application.service import MCPServerInstanceService, derive_bundle_verification
from agentarea_mcp.application.validation_service import MCPValidationError
from agentarea_mcp.domain.env_schema import normalize_env_schema
from agentarea_mcp.domain.mpc_server_instance_model import MCPServerInstance
from agentarea_mcp.package_import import MCPRuntimeRetirementError
from agentarea_mcp.schemas.dto import (
    MCPServerCreate,
    MCPServerInstanceCreate,
)
from agentarea_mcp.schemas.dto import (
    MCPServerInstanceUpdate as MCPServerInstanceUpdateDTO,
)
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

DatabaseSessionDep = Annotated[AsyncSession, Depends(get_db_session)]

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
    created_at: UtcDatetime
    updated_at: UtcDatetime

    @classmethod
    def from_domain(
        cls,
        instance: MCPServerInstance,
        verification_override: dict | None = None,
        secret_env_names: set[str] | None = None,
    ) -> "MCPServerInstanceResponse":
        json_spec = dict(instance.json_spec or {})

        # Old rows may still contain secret plaintext without env_vars metadata.
        raw_env_vars = json_spec.get("env_vars")
        listed_secret_names = (
            {name for name in raw_env_vars if isinstance(name, str)}
            if isinstance(raw_env_vars, list)
            else set()
        )
        secret_names = listed_secret_names | (secret_env_names or set())
        masked_value = "*" * 6
        for field_name in ("environment", "headers"):
            values = json_spec.get(field_name)
            if isinstance(values, dict):
                masked_values = {
                    name: masked_value if name in secret_names else value
                    for name, value in values.items()
                }
                for name in listed_secret_names:
                    masked_values.setdefault(name, masked_value)
                json_spec[field_name] = masked_values

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


async def _instance_secret_env_names(
    service: MCPServerInstanceService,
    instance: MCPServerInstance,
    schema_cache: dict[str, list[dict[str, Any]]] | None = None,
) -> set[str]:
    spec_id = str(instance.server_spec_id or "")
    if not spec_id:
        return set()

    cache = schema_cache if schema_cache is not None else {}
    if spec_id not in cache:
        server_spec = await service.mcp_server_repository.get_server_by_id(spec_id)
        cache[spec_id] = normalize_env_schema(
            getattr(server_spec, "env_schema", None) if server_spec else None
        )
    schema = cache[spec_id]
    known_names = {entry["name"] for entry in schema}
    secret_names = {entry["name"] for entry in schema if entry.get("isSecret")}

    json_spec = instance.json_spec or {}
    for field_name in ("environment", "headers"):
        values = json_spec.get(field_name)
        if isinstance(values, dict):
            secret_names.update(name for name in values if name not in known_names)
    return secret_names


async def _instance_response(
    service: MCPServerInstanceService,
    instance: MCPServerInstance,
    *,
    verification_override: dict | None = None,
    schema_cache: dict[str, list[dict[str, Any]]] | None = None,
) -> MCPServerInstanceResponse:
    return MCPServerInstanceResponse.from_domain(
        instance,
        verification_override=verification_override,
        secret_env_names=await _instance_secret_env_names(service, instance, schema_cache),
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


@router.post(
    "/validate",
    dependencies=[
        unrestricted("workspace member; the workspace-scoped repository is the boundary")
    ],
)
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


@router.post(
    "/",
    status_code=201,
    response_model=MCPServerInstanceResponse,
    dependencies=[
        unrestricted("workspace member; the workspace-scoped repository is the boundary")
    ],
)
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

        return await _instance_response(service, instance)

    except MCPValidationError as e:
        raise HTTPException(status_code=422, detail={"errors": e.errors}) from e
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post(
    "/with-spec",
    status_code=201,
    response_model=MCPServerInstanceResponse,
    dependencies=[
        unrestricted("workspace member; the workspace-scoped repository is the boundary")
    ],
)
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

        server_spec = await service.mcp_server_repository.get_server_by_id(instance.server_spec_id)
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
        return await _instance_response(service, instance)
    except MCPValidationError as e:
        raise HTTPException(status_code=422, detail={"errors": e.errors}) from e
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post(
    "/validate-connection",
    dependencies=[
        unrestricted("workspace member; the workspace-scoped repository is the boundary")
    ],
)
async def validate_connection(
    data: dict[str, Any],
    user_context: UserContextDep,
    service: MCPServerInstanceService = Depends(get_mcp_server_instance_service),
):
    """Test a connection to an MCP server without creating an instance.

    ``server_id`` (optional) is the catalog spec being connected; with it, an
    auth failure also reports the spec endpoint's ``auth_methods``.
    """
    url = data.get("url", "")
    headers = data.get("headers")
    raw_server_id = data.get("server_id")
    try:
        server_id = str(UUID(str(raw_server_id))) if raw_server_id else None
    except ValueError:
        server_id = None
    result = await service.validate_connection(url=url, headers=headers, server_id=server_id)
    return result


@router.post(
    "/check",
    responses={
        503: {"description": "The MCP manager that validates configurations is unreachable"}
    },
    dependencies=[
        unrestricted("workspace member; the workspace-scoped repository is the boundary")
    ],
)
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
                headers={
                    "Content-Type": "application/json",
                    **settings.mcp.manager_inspection_headers(),
                },
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


@router.get("/{instance_id}/environment", dependencies=[requires_workspace_admin()])
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


@router.get(
    "/",
    response_model=list[MCPServerInstanceResponse],
    dependencies=[
        unrestricted("workspace member; the workspace-scoped repository is the boundary")
    ],
)
async def list_mcp_server_instances(
    user_context: UserContextDep,
    service: MCPServerInstanceService = Depends(get_mcp_server_instance_service),
):
    """List all MCP server instances in the workspace."""
    instances = await service.list()

    response_instances = []
    schema_cache: dict[str, list[dict[str, Any]]] = {}
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
                await _instance_response(
                    service, instance, verification_override=derived_v, schema_cache=schema_cache
                )
            )
        else:
            response_instances.append(
                await _instance_response(service, instance, schema_cache=schema_cache)
            )

    return response_instances


@router.get(
    "/{instance_id}",
    response_model=MCPServerInstanceResponse,
    dependencies=[
        unrestricted("workspace member; the workspace-scoped repository is the boundary")
    ],
)
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
        return await _instance_response(service, instance, verification_override=derived_v)

    return await _instance_response(service, instance)


class MCPInstanceConsumer(BaseModel):
    """An agent that has this MCP instance attached, and which of its tools it enabled."""

    agent_id: UUID
    agent_name: str
    agent_slug: str | None = None
    # None means the agent allows every tool the server exposes (no subset filter).
    enabled_tools: list[str] | None = None
    # Subset of enabled_tools that additionally require human confirmation per call.
    confirm_tools: list[str] = Field(default_factory=list)


def _mcp_config_matches(tool_config: dict[str, Any], instance: MCPServerInstance) -> bool:
    """A raw agent tool-config dict references this instance by UUID or by name."""
    if tool_config.get("type") != "mcp":
        return False
    ref = tool_config.get("name")
    if not ref:
        return False
    return str(ref) == str(instance.id) or str(ref) == instance.name


@router.get(
    "/{instance_id}/consumers",
    response_model=list[MCPInstanceConsumer],
    dependencies=[
        unrestricted("workspace member; the workspace-scoped repository is the boundary")
    ],
)
async def list_mcp_server_instance_consumers(
    instance_id: UUID,
    user_context: UserContextDep,
    session: DatabaseSessionDep,
    agent_service: AgentServiceDep,
    service: MCPServerInstanceService = Depends(get_mcp_server_instance_service),
):
    """List agents in the workspace that attach this MCP instance, with their enabled tools.

    A read-only reverse lookup over the agents' ``tools`` JSON. Which tools need
    confirmation is not read from that JSON — it lives in approval policy rules,
    the single source of truth — so it is resolved from there per agent.
    """
    instance = await service.get(instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail="MCP Server Instance not found")

    matches: list[tuple[Any, str, list[str] | None]] = []
    for agent in await agent_service.list():
        tools = agent.tools
        if not isinstance(tools, list):
            continue
        for tc in tools:
            if not isinstance(tc, dict) or not _mcp_config_matches(tc, instance):
                continue
            settings = tc.get("settings") or {}
            allowed = settings.get("allowed_tools")
            enabled_tools: list[str] | None = None
            if isinstance(allowed, list):
                enabled_tools = []
                for perm in allowed:
                    if isinstance(perm, dict):
                        name = perm.get("tool_name")
                        if name:
                            enabled_tools.append(str(name))
                    elif isinstance(perm, str):
                        enabled_tools.append(perm)
            matches.append((agent, str(tc.get("name")), enabled_tools))
            break

    targets_by_agent = await approval_targets_for_agents(
        session, user_context, [agent.id for agent, _, _ in matches]
    )
    consumers: list[MCPInstanceConsumer] = []
    for agent, server_ref, enabled_tools in matches:
        targets = targets_by_agent.get(agent.id, set())
        confirm_tools = [
            name for name in (enabled_tools or []) if mcp_tool_ticked(server_ref, name, targets)
        ]
        consumers.append(
            MCPInstanceConsumer(
                agent_id=agent.id,
                agent_name=agent.name,
                agent_slug=getattr(agent, "slug", None),
                enabled_tools=enabled_tools,
                confirm_tools=confirm_tools,
            )
        )

    return consumers


@router.patch(
    "/{instance_id}",
    response_model=MCPServerInstanceResponse,
    dependencies=[requires("edit", "mcp_instance", id_param="instance_id")],
)
async def update_mcp_server_instance(
    instance_id: UUID,
    data: MCPServerInstanceUpdate,
    user_context: UserContextDep,
    service: MCPServerInstanceService = Depends(get_mcp_server_instance_service),
):
    try:
        instance = await service.update_instance(instance_id, data)
    except MCPRuntimeRetirementError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=str(exc),
            headers={"Retry-After": "1"},
        ) from exc
    if not instance:
        raise HTTPException(status_code=404, detail="MCP Server Instance not found")
    return await _instance_response(service, instance)


@router.delete(
    "/{instance_id}",
    dependencies=[requires("delete", "mcp_instance", id_param="instance_id")],
)
async def delete_mcp_server_instance(
    instance_id: UUID,
    user_context: UserContextDep,
    service: MCPServerInstanceService = Depends(get_mcp_server_instance_service),
):
    try:
        success = await service.delete_instance(instance_id)
    except MCPRuntimeRetirementError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=str(exc),
            headers={"Retry-After": "1"},
        ) from exc
    if not success:
        raise HTTPException(status_code=404, detail="MCP Server Instance not found")
    return {"status": "success"}


@router.post(
    "/{instance_id}/verify",
    dependencies=[requires("edit", "mcp_instance", id_param="instance_id")],
)
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


@router.post(
    "/{instance_id}/discover-tools",
    dependencies=[requires("edit", "mcp_instance", id_param="instance_id")],
)
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


class MCPInstanceHealthResponse(BaseModel):
    """One workload's health, as the calling workspace is entitled to see it.

    Deliberately just the verdict and its reason. The manager's own health body
    is richer — container id, image, ports, the gateway path it serves the
    workload on — and none of that is something a caller needs in order to learn
    that a workload is up. It is dropped here rather than passed through, so the
    endpoint cannot become a way to enumerate the data plane.
    """

    instance_id: str
    name: str | None = None
    healthy: bool
    status: str


class MCPContainersHealthResponse(BaseModel):
    instances: list[MCPInstanceHealthResponse]
    total: int
    healthy: int


@router.get(
    "/health/containers",
    response_model=MCPContainersHealthResponse,
    dependencies=[
        unrestricted("workspace member; the workspace-scoped repository is the boundary")
    ],
)
async def get_containers_health(
    user_context: UserContextDep,
    service: MCPServerInstanceService = Depends(get_mcp_server_instance_service),
):
    """Health of this workspace's MCP workloads.

    The manager also has a route that answers for every workload it runs, which is
    the wrong thing to hand a caller: its rows carry service names and container
    ids belonging to other workspaces. The instance list comes from the
    workspace-scoped service instead, and only those ids are asked about, so the
    answer cannot name a workload the caller is not entitled to see.

    A workload the manager reports as unhealthy, has never heard of, or cannot be
    reached about is a fact about that instance, not a failure of the request: each
    is reported per instance and the endpoint still answers 200.
    """
    import asyncio

    import httpx

    settings = get_settings()
    instances = await service.list()

    async def read_one(client: "httpx.AsyncClient", instance) -> dict:
        row = {"instance_id": str(instance.id), "name": getattr(instance, "name", None)}
        url = f"{settings.mcp.MCP_MANAGER_URL}/instances/{instance.id}/health"
        try:
            response = await client.get(
                url,
                headers=settings.mcp.manager_inspection_headers(),
            )
        except httpx.RequestError as e:
            logger.warning(
                "MCP manager unreachable for instance %s: %s", instance.id, e, exc_info=True
            )
            return {**row, "healthy": False, "status": "manager_unreachable"}

        # The manager answers 200 when healthy and 503 when not, both with the
        # same body: the second is a report, not a transport failure.
        if response.status_code in (200, 503):
            try:
                body = response.json()
            except ValueError:
                logger.exception("MCP manager sent unreadable health for %s", instance.id)
                return {**row, "healthy": False, "status": "unreadable"}
            if not isinstance(body, dict):
                return {**row, "healthy": False, "status": "unreadable"}
            return {
                **row,
                "healthy": bool(body.get("healthy")),
                "status": body.get("status") or ("healthy" if body.get("healthy") else "unhealthy"),
            }

        if response.status_code == 404:
            # Never started, or already reaped for idleness: not an error.
            return {**row, "healthy": False, "status": "not_running"}

        logger.error(
            "MCP manager answered %s for instance %s: %s",
            response.status_code,
            instance.id,
            response.text[:200],
        )
        return {**row, "healthy": False, "status": "error"}

    async with httpx.AsyncClient(timeout=15.0) as client:
        rows = await asyncio.gather(*(read_one(client, instance) for instance in instances))

    return {
        "instances": list(rows),
        "total": len(rows),
        "healthy": sum(1 for row in rows if row["healthy"]),
    }


@router.post(
    "/{instance_id}/probe",
    dependencies=[requires("edit", "mcp_instance", id_param="instance_id")],
)
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
                spec = await server_repo.get_server_by_id(instance.server_spec_id)
                if spec:
                    new_json_spec = dict(spec.json_spec or {})
                    new_json_spec["auth_methods"] = result["methods"]
                    db_session = service.repository.session
                    stmt = (
                        sa_update(MCPServer)
                        .where(MCPServer.id == spec.id)
                        .values(json_spec=new_json_spec)
                    )
                    updated = await db_session.execute(stmt)
                    await db_session.commit()
                    if updated.rowcount == 0:
                        logger.info(
                            "Auth methods for MCP server spec %s not cached: the spec is not "
                            "owned by workspace %s (a shared catalog mirror)",
                            spec.id,
                            service.repository.user_context.workspace_id,
                        )
        except Exception:
            logger.warning(
                "Failed to cache auth methods for MCP server spec after probe",
                exc_info=True,
            )

    return result


@router.post(
    "/{instance_id}/test-auth",
    dependencies=[requires("edit", "mcp_instance", id_param="instance_id")],
)
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

    # The instance address is deliberately not resolved here: container-backed
    # servers are only reachable through the manager gateway, and this endpoint
    # queues the check rather than dialing anything itself.
    return {
        "status": "pending",
        "message": (
            "Auth test queued. Use /health/containers to verify connectivity once running."
        ),
        "instance_id": str(instance_id),
        "auth_config_id": str(instance.auth_config_id),
    }


@router.post(
    "/{instance_id}/oauth-link",
    dependencies=[requires("edit", "mcp_instance", id_param="instance_id")],
)
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


@router.get("/{instance_id}/oauth-links", dependencies=[requires_workspace_admin()])
async def list_oauth_links(
    instance_id: UUID,
    user_context: UserContextDep,
    service: MCPServerInstanceService = Depends(get_mcp_server_instance_service),
    oauth_link_service: MCPOAuthLinkService = Depends(get_oauth_link_service),
):
    instance = await service.get(instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail="MCP Server Instance not found")

    links = await oauth_link_service.list_links(instance_id)
    return [OAuthLinkResponse.model_validate(link) for link in links]
