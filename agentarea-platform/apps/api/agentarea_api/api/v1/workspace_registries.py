"""A workspace's own registries (ADR-0044).

A workspace admin points one at an index in the platform format or at a GitHub
repository of skills; only that workspace sees its items. Members read them;
changing, syncing or removing one is the admin's. The platform's registries
are written through ``/registries`` by the platform workspace only.
"""

from typing import Literal
from uuid import UUID

from agentarea_api.api.deps.services import SecretCatalogServiceDep, get_registry_service
from agentarea_api.api.v1.registries import RegistryResponse, SyncResponse
from agentarea_api.registry_credentials import REGISTRY_SECRET_CONSUMER, REGISTRY_SECRET_FIELD
from agentarea_common.auth.dependencies import UserContextDep
from agentarea_common.auth.route_authz import requires_workspace_admin, unrestricted
from agentarea_registry.application.service import RegistryNotFoundError, RegistryService
from agentarea_secrets.catalog_service import (
    ManagedSecretError,
    SecretAccessDeniedError,
    SecretCatalogService,
    SecretNotFoundError,
)
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError

router = APIRouter(prefix="/workspace-registries", tags=["registries"])


class WorkspaceRegistryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    registry_type: Literal["skills", "agents"] = "skills"
    source_type: Literal["url", "github"] = Field(
        ..., description="'url': an index in the platform format; 'github': a repository"
    )
    source_url: str = Field(
        ..., min_length=1, description="The index URL, or the repository as owner/repo"
    )
    source_ref: str | None = Field(
        None,
        max_length=255,
        description="GitHub: branch, tag or commit; the default branch if unset",
    )
    source_path: str | None = Field(
        None, description="GitHub: the folder whose skill folders are indexed; the root if unset"
    )
    trust: Literal["private", "community"] = "private"
    mode: Literal["mirror", "upstream"] = Field(
        "mirror",
        description=(
            "'mirror' stores every skill's content when the registry syncs, so an install "
            "needs no network; 'upstream' fetches it on first install. A source read with "
            "credentials is mirrored."
        ),
    )
    credentials_secret_id: UUID | None = Field(
        None, description="A workspace secret holding the token a private source is read with"
    )


class WorkspaceRegistryUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    source_url: str | None = Field(None, min_length=1)
    source_ref: str | None = Field(None, max_length=255)
    source_path: str | None = None
    is_active: bool | None = None
    trust: Literal["private", "community"] | None = None
    mode: Literal["mirror", "upstream"] | None = None
    credentials_secret_id: UUID | None = None


async def _usable_secret(secrets: SecretCatalogService, secret_id: UUID) -> UUID:
    try:
        return (await secrets.get_for_use(secret_id)).id
    except SecretNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except (ManagedSecretError, SecretAccessDeniedError) as e:
        raise HTTPException(status_code=403, detail=str(e)) from e


async def _own_registry(service: RegistryService, registry_id: UUID, workspace_id: str):
    registry = await service.get_workspace_registry(registry_id, workspace_id)
    if registry is None:
        raise HTTPException(status_code=404, detail="Registry not found")
    return registry


@router.get(
    "",
    response_model=list[RegistryResponse],
    dependencies=[unrestricted("workspace member; lists only this workspace's registries")],
)
async def list_workspace_registries(
    user_context: UserContextDep,
    service: RegistryService = Depends(get_registry_service),
):
    registries = await service.list_visible_registries(scope="workspace")
    return [RegistryResponse.from_domain(r) for r in registries]


@router.post(
    "",
    response_model=RegistryResponse,
    status_code=201,
    dependencies=[requires_workspace_admin()],
)
async def create_workspace_registry(
    data: WorkspaceRegistryCreate,
    user_context: UserContextDep,
    secrets: SecretCatalogServiceDep,
    service: RegistryService = Depends(get_registry_service),
):
    secret_id = (
        await _usable_secret(secrets, data.credentials_secret_id)
        if data.credentials_secret_id
        else None
    )
    try:
        registry = await service.create_registry(
            name=data.name,
            registry_type=data.registry_type,
            source_type=data.source_type,
            source_url=data.source_url,
            description=data.description,
            scope="workspace",
            workspace_id=user_context.workspace_id,
            mode=data.mode,
            trust=data.trust,
            credentials_secret_ref=secret_id,
            source_ref=data.source_ref,
            source_path=data.source_path,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except IntegrityError as e:
        raise HTTPException(
            status_code=409, detail=f"This workspace already has a registry named {data.name!r}"
        ) from e
    if secret_id:
        await secrets.add_reference(
            secret_id, REGISTRY_SECRET_CONSUMER, str(registry.id), REGISTRY_SECRET_FIELD
        )
    return RegistryResponse.from_domain(registry)


@router.get(
    "/{registry_id}",
    response_model=RegistryResponse,
    dependencies=[unrestricted("workspace member; another workspace's registry is not found")],
)
async def get_workspace_registry(
    registry_id: UUID,
    user_context: UserContextDep,
    service: RegistryService = Depends(get_registry_service),
):
    return RegistryResponse.from_domain(
        await _own_registry(service, registry_id, user_context.workspace_id)
    )


@router.patch(
    "/{registry_id}",
    response_model=RegistryResponse,
    dependencies=[requires_workspace_admin()],
)
async def update_workspace_registry(
    registry_id: UUID,
    data: WorkspaceRegistryUpdate,
    user_context: UserContextDep,
    secrets: SecretCatalogServiceDep,
    service: RegistryService = Depends(get_registry_service),
):
    await _own_registry(service, registry_id, user_context.workspace_id)
    fields = data.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")
    if "credentials_secret_id" in fields:
        secret_id = fields.pop("credentials_secret_id")
        fields["credentials_secret_ref"] = (
            await _usable_secret(secrets, secret_id) if secret_id else None
        )
    try:
        registry = await service.update_registry(registry_id, **fields)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except IntegrityError as e:
        raise HTTPException(status_code=409, detail="A registry with that name exists") from e
    if registry is None:
        raise HTTPException(status_code=404, detail="Registry not found")
    if "credentials_secret_ref" in fields:
        await secrets.clear_references(REGISTRY_SECRET_CONSUMER, str(registry_id))
        if registry.credentials_secret_ref:
            await secrets.add_reference(
                registry.credentials_secret_ref,
                REGISTRY_SECRET_CONSUMER,
                str(registry_id),
                REGISTRY_SECRET_FIELD,
            )
    return RegistryResponse.from_domain(registry)


class WorkspaceRegistryRemoved(BaseModel):
    # "deleted", or "retired" while installed or forked items still point at it:
    # those keep working and their rows stay, out of the catalog.
    status: Literal["deleted", "retired"]
    kept_items: int


@router.delete(
    "/{registry_id}",
    response_model=WorkspaceRegistryRemoved,
    dependencies=[requires_workspace_admin()],
)
async def delete_workspace_registry(
    registry_id: UUID,
    user_context: UserContextDep,
    secrets: SecretCatalogServiceDep,
    service: RegistryService = Depends(get_registry_service),
):
    """Remove the registry, or retire it while something still uses its items."""
    await _own_registry(service, registry_id, user_context.workspace_id)
    await service.retire_registry(registry_id)
    kept = await service.count_items(registry_id)
    if kept:
        return WorkspaceRegistryRemoved(status="retired", kept_items=kept)
    await secrets.clear_references(REGISTRY_SECRET_CONSUMER, str(registry_id))
    await service.delete_registry(registry_id)
    return WorkspaceRegistryRemoved(status="deleted", kept_items=0)


@router.post(
    "/{registry_id}/sync",
    response_model=SyncResponse,
    dependencies=[requires_workspace_admin()],
)
async def sync_workspace_registry(
    registry_id: UUID,
    user_context: UserContextDep,
    force: bool = False,
    service: RegistryService = Depends(get_registry_service),
):
    await _own_registry(service, registry_id, user_context.workspace_id)
    try:
        return SyncResponse(**await service.sync_registry(registry_id, force=force))
    except RegistryNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Sync failed: {e}") from e
