"""Egress exits: the proxies a workspace's MCP instances may leave through.

The workspace defines its own (a customer or purchased proxy); the platform's are
listed beside them and can be bound but not changed. An instance binds one with
``json_spec.egress_exit = "<exit id>"``. Enforcing the binding takes the
enterprise edition; without it a bound instance does not start.
"""

from typing import Annotated
from uuid import UUID

from agentarea_api.api.deps.services import get_egress_exit_service
from agentarea_common.auth.route_authz import requires, unrestricted
from agentarea_common.utils.types import UtcDatetime
from agentarea_mcp.application.egress_exit_service import (
    EgressExitInUseError,
    EgressExitNotFoundError,
    EgressExitService,
    EgressExitValidationError,
    PlatformEgressExitError,
)
from agentarea_mcp.domain.egress_exit_model import EgressExit
from agentarea_mcp.schemas.egress_exit_dto import EgressExitCreate, EgressExitUpdate
from agentarea_secrets.catalog_service import (
    ManagedSecretError,
    SecretAccessDeniedError,
    SecretNotFoundError,
)
from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/egress-exits", tags=["egress-exits"])

EgressExitServiceDep = Annotated[EgressExitService, Depends(get_egress_exit_service)]


class EgressExitResponse(BaseModel):
    id: UUID
    name: str
    description: str | None
    upstream_url: str | None
    username: str | None
    password_secret_id: UUID | None
    via: str | None = Field(description="The platform hop this exit leaves through, if any.")
    allow_plaintext_credentials: bool
    managed_by: str | None = Field(
        description='"platform" for an exit the deployment supplies; null for the workspace\'s own.'
    )
    created_by: str
    created_at: UtcDatetime
    updated_at: UtcDatetime

    @classmethod
    def from_model(cls, exit_: EgressExit) -> EgressExitResponse:
        return cls(
            id=exit_.id,
            name=exit_.name,
            description=exit_.description,
            upstream_url=exit_.upstream_url,
            username=exit_.username,
            password_secret_id=exit_.password_secret_id,
            via=exit_.via,
            allow_plaintext_credentials=exit_.allow_plaintext_credentials,
            managed_by=exit_.managed_by,
            created_by=exit_.created_by,
            created_at=exit_.created_at,
            updated_at=exit_.updated_at,
        )


def _secret_error(e: Exception) -> HTTPException:
    if isinstance(e, SecretNotFoundError):
        return HTTPException(status_code=400, detail=str(e))
    return HTTPException(status_code=403, detail=str(e))


@router.get(
    "/",
    response_model=list[EgressExitResponse],
    dependencies=[
        unrestricted(
            "workspace member; the workspace-scoped repository is the boundary, "
            "and platform exits are readable by every workspace"
        )
    ],
)
async def list_egress_exits(service: EgressExitServiceDep) -> list[EgressExitResponse]:
    """List the workspace's own exits and the platform's."""
    return [EgressExitResponse.from_model(e) for e in await service.list()]


@router.post(
    "/",
    response_model=EgressExitResponse,
    status_code=201,
    dependencies=[
        unrestricted("workspace member; the workspace-scoped repository is the boundary")
    ],
)
async def create_egress_exit(
    service: EgressExitServiceDep,
    payload: EgressExitCreate = Body(...),
) -> EgressExitResponse:
    """Define a proxy the workspace's MCP instances may leave through."""
    try:
        return EgressExitResponse.from_model(await service.create(payload))
    except EgressExitValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except (SecretNotFoundError, SecretAccessDeniedError, ManagedSecretError) as e:
        raise _secret_error(e) from e


@router.get(
    "/{exit_id}",
    response_model=EgressExitResponse,
    dependencies=[
        unrestricted("workspace member; the workspace-scoped repository is the boundary")
    ],
)
async def get_egress_exit(exit_id: UUID, service: EgressExitServiceDep) -> EgressExitResponse:
    """Get an exit of the workspace or the platform."""
    try:
        return EgressExitResponse.from_model(await service.get(exit_id))
    except EgressExitNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.patch(
    "/{exit_id}",
    response_model=EgressExitResponse,
    dependencies=[requires("edit", "egress_exit", id_param="exit_id")],
)
async def update_egress_exit(
    exit_id: UUID,
    service: EgressExitServiceDep,
    payload: EgressExitUpdate = Body(...),
) -> EgressExitResponse:
    """Change an exit; only the fields sent change.

    Changing where it leads or its credentials restarts the running instances bound to it.
    """
    try:
        return EgressExitResponse.from_model(await service.update(exit_id, payload))
    except EgressExitNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except PlatformEgressExitError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except EgressExitValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except (SecretNotFoundError, SecretAccessDeniedError, ManagedSecretError) as e:
        raise _secret_error(e) from e


@router.delete(
    "/{exit_id}",
    status_code=204,
    dependencies=[requires("delete", "egress_exit", id_param="exit_id")],
)
async def delete_egress_exit(exit_id: UUID, service: EgressExitServiceDep) -> None:
    """Delete an exit no MCP instance leaves through."""
    try:
        await service.delete(exit_id)
    except EgressExitNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except PlatformEgressExitError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except EgressExitInUseError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
