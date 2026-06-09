"""API routes for registries — unified catalog for MCP servers and skills.

Sync auto-creates entities for new items. Version updates are manual.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from agentarea_api.api.deps.services import get_registry_service
from agentarea_common.auth.dependencies import UserContextDep
from agentarea_registry.application.service import RegistryService
from agentarea_registry.domain.models import Registry, RegistryItem
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

router = APIRouter(prefix="/registries", tags=["registries"])


# ── Schemas ──


class RegistryCreate(BaseModel):
    name: str = Field(..., description="Human-readable registry name")
    description: str | None = Field(None)
    registry_type: str = Field(..., description="Entity type: 'mcp_servers' or 'skills'")
    source_type: str = Field(..., description="Fetch method: 'url', 'github', or 'api'")
    source_url: str = Field(..., description="URL to the registry source (JSON or YAML)")
    sync_mode: str = Field(default="manual", description="'auto' or 'manual'")


class RegistryUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    source_url: str | None = None
    sync_mode: str | None = None
    is_active: bool | None = None


class RegistryResponse(BaseModel):
    id: UUID
    name: str
    description: str | None
    registry_type: str
    source_type: str
    source_url: str
    sync_mode: str
    is_active: bool
    last_synced_at: datetime | None
    last_sync_error: str | None
    item_count: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, r: Registry) -> "RegistryResponse":
        return cls(
            id=r.id,
            name=r.name,
            description=r.description,
            registry_type=r.registry_type,
            source_type=r.source_type,
            source_url=r.source_url,
            sync_mode=r.sync_mode,
            is_active=r.is_active,
            last_synced_at=r.last_synced_at,
            last_sync_error=r.last_sync_error,
            item_count=r.item_count,
            created_at=r.created_at,
            updated_at=r.updated_at,
        )


class RegistryItemResponse(BaseModel):
    id: UUID
    registry_id: UUID
    external_id: str
    name: str
    description: str | None
    version: str | None
    spec: dict[str, Any]
    tags: list[str]
    installed_entity_id: UUID | None
    update_available: bool
    installed_version: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, item: RegistryItem) -> "RegistryItemResponse":
        return cls(
            id=item.id,
            registry_id=UUID(str(item.registry_id)),
            external_id=item.external_id,
            name=item.name,
            description=item.description,
            version=item.version,
            spec=item.spec or {},
            tags=item.tags or [],
            installed_entity_id=UUID(str(item.installed_entity_id))
            if item.installed_entity_id
            else None,
            update_available=item.update_available,
            installed_version=item.installed_version,
            created_at=item.created_at,
            updated_at=item.updated_at,
        )


class SyncResponse(BaseModel):
    new_specs: int
    updates_flagged: int
    unchanged: int
    total: int


class UpdateAllResponse(BaseModel):
    updated: int
    errors: int


async def require_platform_catalog_write(user_context: UserContextDep) -> None:
    """ReBAC guard for mutating the global registry catalog.

    Registries/registry_items are global, platform-owned catalog infrastructure
    (ADR-003) — they have no per-workspace owner. Writing them therefore requires
    write access to the platform scope, decided by the AuthorizationService (the
    ReBAC abstraction: own-workspace rule in OSS, Keto relations in enterprise).
    No RBAC roles are involved. Reads stay open so every workspace sees built-ins.
    """
    from agentarea_common.auth.authorization import AuthorizationService
    from agentarea_common.constants import PLATFORM_WORKSPACE_ID
    from agentarea_common.di.container import resolve

    authz = resolve(AuthorizationService)
    if not await authz.can_write_workspace(user_context, PLATFORM_WORKSPACE_ID):
        raise HTTPException(
            status_code=403,
            detail="Only the platform may modify the global registry catalog",
        )


# ── Registry CRUD ──


@router.post(
    "/",
    response_model=RegistryResponse,
    dependencies=[Depends(require_platform_catalog_write)],
)
async def create_registry(
    data: RegistryCreate,
    user_context: UserContextDep,
    service: RegistryService = Depends(get_registry_service),
):
    try:
        registry = await service.create_registry(
            name=data.name,
            registry_type=data.registry_type,
            source_type=data.source_type,
            source_url=data.source_url,
            description=data.description,
            sync_mode=data.sync_mode,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return RegistryResponse.from_domain(registry)


@router.get("/", response_model=list[RegistryResponse])
async def list_registries(
    user_context: UserContextDep,
    active_only: bool = Query(False),
    registry_type: str | None = Query(None),
    service: RegistryService = Depends(get_registry_service),
):
    registries = await service.list_registries(active_only=active_only, registry_type=registry_type)
    return [RegistryResponse.from_domain(r) for r in registries]


@router.get("/catalog/search", response_model=list[RegistryItemResponse])
async def search_catalog(
    user_context: UserContextDep,
    q: str | None = Query(None, description="Search query"),
    tag: str | None = Query(None),
    update_available: bool | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    service: RegistryService = Depends(get_registry_service),
):
    """Search across all registry catalogs in the workspace."""
    items = await service.search_catalog(
        query=q,
        tag=tag,
        update_available=update_available,
        limit=limit,
        offset=offset,
    )
    return [RegistryItemResponse.from_domain(i) for i in items]


@router.get("/{registry_id}", response_model=RegistryResponse)
async def get_registry(
    registry_id: UUID,
    user_context: UserContextDep,
    service: RegistryService = Depends(get_registry_service),
):
    registry = await service.get_registry(registry_id)
    if not registry:
        raise HTTPException(status_code=404, detail="Registry not found")
    return RegistryResponse.from_domain(registry)


@router.patch(
    "/{registry_id}",
    response_model=RegistryResponse,
    dependencies=[Depends(require_platform_catalog_write)],
)
async def update_registry(
    registry_id: UUID,
    data: RegistryUpdate,
    user_context: UserContextDep,
    service: RegistryService = Depends(get_registry_service),
):
    fields = data.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")
    registry = await service.update_registry(registry_id, **fields)
    if not registry:
        raise HTTPException(status_code=404, detail="Registry not found")
    return RegistryResponse.from_domain(registry)


@router.delete(
    "/{registry_id}",
    dependencies=[Depends(require_platform_catalog_write)],
)
async def delete_registry(
    registry_id: UUID,
    user_context: UserContextDep,
    service: RegistryService = Depends(get_registry_service),
):
    success = await service.delete_registry(registry_id)
    if not success:
        raise HTTPException(status_code=404, detail="Registry not found")
    return {"status": "deleted"}


# ── Sync ──


@router.post(
    "/{registry_id}/sync",
    response_model=SyncResponse,
    dependencies=[Depends(require_platform_catalog_write)],
)
async def sync_registry(
    registry_id: UUID,
    user_context: UserContextDep,
    service: RegistryService = Depends(get_registry_service),
):
    """Sync: fetch source, auto-create entities for new items, flag version updates."""
    try:
        stats = await service.sync_registry(registry_id)
        return SyncResponse(**stats)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Sync failed: {e}") from e


# ── Catalog items ──


@router.get("/{registry_id}/items", response_model=list[RegistryItemResponse])
async def list_registry_items(
    registry_id: UUID,
    user_context: UserContextDep,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    service: RegistryService = Depends(get_registry_service),
):
    items = await service.list_items(registry_id, limit=limit, offset=offset)
    return [RegistryItemResponse.from_domain(i) for i in items]


@router.get("/catalog/items/{item_id}", response_model=RegistryItemResponse)
async def get_catalog_item(
    item_id: UUID,
    user_context: UserContextDep,
    service: RegistryService = Depends(get_registry_service),
):
    item = await service.get_item(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Catalog item not found")
    return RegistryItemResponse.from_domain(item)


# ── Update specs ──


@router.post(
    "/catalog/items/{item_id}/update",
    dependencies=[Depends(require_platform_catalog_write)],
)
async def update_item_spec(
    item_id: UUID,
    user_context: UserContextDep,
    service: RegistryService = Depends(get_registry_service),
):
    """Apply the latest registry version to this item's entity."""
    try:
        await service.update_item_spec(item_id)
        return {"status": "updated"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post(
    "/{registry_id}/update-all",
    response_model=UpdateAllResponse,
    dependencies=[Depends(require_platform_catalog_write)],
)
async def update_all_specs(
    registry_id: UUID,
    user_context: UserContextDep,
    service: RegistryService = Depends(get_registry_service),
):
    """Bulk-update all items with pending version updates."""
    result = await service.update_all_specs(registry_id)
    return UpdateAllResponse(**result)
