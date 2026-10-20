"""Skills API endpoints for managing agent skills."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated, Any, Literal, cast
from uuid import UUID

from agentarea_agents.application.skill_parser import SkillFrontmatterError
from agentarea_agents.application.skill_service import (
    SkillCustomizedError,
    SkillNotFromCatalogError,
    SkillService,
    SkillUpdateResult,
    SkillVersionNotFoundError,
    is_customized,
)
from agentarea_agents.domain.skill_models import Skill, SkillVersion
from agentarea_agents.infrastructure.catalog_skill_repository import CatalogProvenance
from agentarea_agents.infrastructure.github_skill_importer import (
    GitHubNotFoundError,
    GitHubRateLimitError,
    GitHubSkillImporterError,
    GitHubSourceGoneError,
    GitHubTreeMismatchError,
)
from agentarea_agents.schemas.skills_dto import (
    SkillCreateFromContent,
    SkillEditMetadata,
    SkillImportFromGithub,
)
from agentarea_common.auth.dependencies import UserContextDep
from agentarea_common.auth.permission import require_permission
from agentarea_common.auth.resource_visibility import readable_resource_ids
from agentarea_common.auth.route_authz import (
    enforced_in_handler,
    requires,
    requires_workspace_admin,
    unrestricted,
)
from agentarea_common.base import RepositoryFactoryDep
from agentarea_common.base.pagination import PaginatedResponse, PaginationParams
from agentarea_common.exceptions.errors import AppError, NotFoundError
from agentarea_common.utils.types import utc_isoformat
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from ._access_control_grants import grant_resource_owner
from .registries import RegistryScope, RegistryTrust

router = APIRouter(prefix="/skills", tags=["skills"])


# ============================================================================
# Service Dependency
# ============================================================================


async def get_skill_service(
    repository_factory: RepositoryFactoryDep,
    user_context: UserContextDep,
) -> SkillService:
    """Get a SkillService instance for the current request."""
    return SkillService(
        repository_factory=repository_factory,
        user_context=user_context,
    )


SkillServiceDep = Annotated[SkillService, Depends(get_skill_service)]


# ============================================================================
# Request/Response Models
# ============================================================================


class SkillCreateRequest(BaseModel):
    """Request to create a skill."""

    content: str | None = Field(None, description="Raw markdown content")
    github_url: str | None = Field(None, description="GitHub repository URL")
    name: str | None = Field(None, max_length=255, description="Optional name override")
    description: str | None = Field(
        None, max_length=1000, description="Optional description override"
    )

    def model_post_init(self, __context) -> None:
        """Validate that exactly one source is provided."""
        if not self.content and not self.github_url:
            raise ValueError("Either 'content' or 'github_url' must be provided")
        if self.content and self.github_url:
            raise ValueError("Only one of 'content' or 'github_url' can be provided")


class SkillUpdateRequest(BaseModel):
    """Request to update a skill."""

    name: str | None = Field(None, min_length=1, max_length=255, description="New name")
    description: str | None = Field(None, max_length=1000, description="New description")
    content: str | None = Field(None, description="New content (only for content-type skills)")


class SkillResponse(BaseModel):
    """Skill response model."""

    id: str
    name: str
    slug: str
    description: str | None
    source_type: str
    source_url: str | None
    network_scope: str
    workspace_id: str
    created_at: str
    updated_at: str
    # Catalog provenance (ADR-003). ``is_catalog`` marks a read-only built-in
    # skill that has not been forked into the workspace yet.
    is_catalog: bool = False
    registry_item_id: str | None = None
    # The catalog item moved past the version this install is pinned to.
    update_available: bool = False
    # The workspace edited this installed skill; an update would discard that.
    customized: bool = False
    # The registry an installed skill's catalog item comes from (ADR-0044).
    registry_name: str | None = None
    registry_scope: RegistryScope | None = None
    registry_trust: RegistryTrust | None = None
    # Its source no longer publishes the item (or the registry was retired);
    # the installed skill keeps working.
    removed_upstream: bool = False

    @classmethod
    def from_skill(cls, skill: Skill) -> SkillResponse:
        """Create response from Skill entity."""
        network_scope = getattr(skill, "network_scope", "private")
        if not isinstance(network_scope, str):
            network_scope = "private"

        registry_item_id = getattr(skill, "registry_item_id", None)
        provenance = getattr(skill, "catalog_provenance", None)
        if not isinstance(provenance, CatalogProvenance):
            provenance = None
        return cls(
            id=str(skill.id),
            name=skill.name,
            slug=skill.slug,
            description=skill.description,
            source_type=skill.source_type,
            source_url=skill.source_url,
            network_scope=network_scope,
            workspace_id=getattr(skill, "workspace_id", "") or "",
            created_at=utc_isoformat(skill.created_at) if skill.created_at else "",
            updated_at=utc_isoformat(skill.updated_at) if skill.updated_at else "",
            is_catalog=bool(getattr(skill, "is_catalog", False)),
            registry_item_id=str(registry_item_id) if registry_item_id else None,
            update_available=bool(getattr(skill, "update_available", False)),
            customized=is_customized(skill),
            registry_name=provenance.registry_name if provenance else None,
            registry_scope=cast(RegistryScope, provenance.registry_scope) if provenance else None,
            registry_trust=cast(RegistryTrust, provenance.registry_trust) if provenance else None,
            removed_upstream=bool(provenance and provenance.removed_upstream),
        )


class SkillUpdateResultResponse(BaseModel):
    """What updating one installed skill did."""

    skill_id: str
    name: str
    status: Literal["updated", "up_to_date", "customized", "failed"]
    error: str | None = None
    skill: SkillResponse | None = None

    @classmethod
    def from_result(cls, result: SkillUpdateResult) -> SkillUpdateResultResponse:
        return cls(
            skill_id=result.skill_id,
            name=result.name,
            status=result.status,
            error=result.error,
            skill=SkillResponse.from_skill(result.skill) if result.skill else None,
        )


class SkillUpdateAllResponse(BaseModel):
    """One result per installed skill that had an update."""

    results: list[SkillUpdateResultResponse]


class SkillVersionResponse(BaseModel):
    """One package a skill pointed at; the last is what it runs now."""

    id: str
    digest: str | None
    reason: Literal["create", "edit", "install", "update", "rollback", "migrate", "refresh"]
    # The catalog item version an installed package was pinned at, or the
    # source commit a refresh read.
    catalog_version: str | None = None
    created_by: str
    created_at: str
    current: bool

    @classmethod
    def from_version(cls, version: SkillVersion, current: bool) -> SkillVersionResponse:
        return cls(
            id=str(version.id),
            digest=version.digest,
            reason=cast(Any, version.reason),
            catalog_version=version.catalog_version,
            created_by=version.created_by,
            created_at=utc_isoformat(version.created_at),
            current=current,
        )


class SkillContentResponse(BaseModel):
    """Skill content response model."""

    id: str
    name: str
    content: str


class SkillFileResponse(BaseModel):
    """Skill file info response model."""

    path: str
    size: int
    url: str | None = None


class SkillFilesResponse(BaseModel):
    """Skill files list response model."""

    skill_id: str
    files: list[SkillFileResponse]


class SkillMemberAddRequest(BaseModel):
    """Request to add a child skill member."""

    child_skill_id: UUID = Field(..., description="ID of the child skill to add")
    order: int = Field(
        0,
        ge=-(2**31),
        le=2**31 - 1,
        description="Execution order hint (a 32-bit integer)",
    )
    is_required: bool = Field(True, description="Whether this child is required")
    dependencies: list[str] = Field(
        default_factory=list,
        description="IDs of sibling children that must run before this one",
    )


class SkillMemberResponse(BaseModel):
    """Skill member response model."""

    parent_skill_id: str
    child_skill_id: str
    order: int
    is_required: bool
    dependencies: list[str]


@contextmanager
def _source_errors() -> Iterator[None]:
    """Answer a failed fetch of a catalog skill's source with what went wrong."""
    try:
        yield
    except GitHubSourceGoneError as e:
        raise AppError(str(e), status_code=410, code="skill_source_gone") from e
    except GitHubRateLimitError as e:
        raise AppError(str(e), status_code=429, code="github_rate_limited") from e
    except GitHubTreeMismatchError as e:
        raise AppError(str(e), status_code=409, code="skill_tree_mismatch") from e
    except GitHubSkillImporterError as e:
        raise AppError(str(e), status_code=502, code="skill_source_unreachable") from e


@contextmanager
def _catalog_fetch_errors() -> Iterator[None]:
    """Answer a failed install or update of a catalog skill with what went wrong."""
    try:
        with _source_errors():
            yield
    except SkillCustomizedError as e:
        raise AppError(str(e), status_code=409, code="skill_customized") from e
    except SkillNotFromCatalogError as e:
        raise AppError(str(e), status_code=409, code="skill_not_from_catalog") from e
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail="Skill not found") from e
    except SkillFrontmatterError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


# ============================================================================
# Endpoints
# ============================================================================


@router.post(
    "",
    response_model=SkillResponse,
    dependencies=[
        unrestricted("workspace member; the workspace-scoped repository is the boundary")
    ],
)
async def create_skill(
    request: SkillCreateRequest,
    skill_service: SkillServiceDep,
):
    """Create a new skill from content or GitHub URL."""
    try:
        if request.content:
            skill = await skill_service.create_from_content(
                SkillCreateFromContent(
                    content=request.content,
                    name=request.name,
                    description=request.description,
                ),
            )
        else:
            if request.github_url is None:
                raise HTTPException(status_code=400, detail="github_url is required")
            skill = await skill_service.create_from_github(
                SkillImportFromGithub(
                    github_url=request.github_url,
                    name=request.name,
                    description=request.description,
                ),
            )

        await grant_resource_owner(
            resource_id=skill.id,
            workspace_id=skill_service.user_context.workspace_id,
            user_id=skill_service.user_context.user_id,
        )
        return SkillResponse.from_skill(skill)

    except GitHubRateLimitError as e:
        raise HTTPException(status_code=429, detail=str(e)) from e
    except GitHubNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except GitHubSkillImporterError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except SkillFrontmatterError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post(
    "/upload",
    response_model=SkillResponse,
    dependencies=[
        unrestricted("workspace member; the workspace-scoped repository is the boundary")
    ],
)
async def upload_skill(
    skill_service: SkillServiceDep,
    file: UploadFile = File(..., description="ZIP file containing the skill package"),
    name: str | None = Query(None, max_length=255),
    description: str | None = Query(None, max_length=1000),
):
    """Upload a skill package as a ZIP file."""
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="File must be a ZIP archive")

    try:
        content = await file.read()
        skill = await skill_service.create_from_zip(
            zip_data=content,
            name=name,
            description=description,
        )
        await grant_resource_owner(
            resource_id=skill.id,
            workspace_id=skill_service.user_context.workspace_id,
            user_id=skill_service.user_context.user_id,
        )
        return SkillResponse.from_skill(skill)

    except SkillFrontmatterError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get(
    "",
    response_model=PaginatedResponse[SkillResponse],
    dependencies=[
        enforced_in_handler("the tenant half is narrowed to what the graph says is readable")
    ],
)
async def list_skills(
    skill_service: SkillServiceDep,
    user_context: UserContextDep,
    pagination: PaginationParams = Depends(),
    source_type: str | None = Query(None, description="Filter by source type"),
    network_scope: str | None = Query(None, description="Filter by network scope"),
    from_registry: bool | None = Query(None, description="Filter registry-created skills"),
    include_catalog: bool = Query(
        True, description="Merge in catalog skills not installed in the workspace"
    ),
):
    """List skills in the workspace."""
    skills, total = await skill_service.list_paginated(
        limit=pagination.limit,
        offset=pagination.offset,
        search=pagination.search,
        source_type=source_type,
        network_scope=network_scope,
        from_registry=from_registry,
        include_catalog=include_catalog,
        ids=await readable_resource_ids(user_context.user_id),
    )
    return PaginatedResponse(
        items=[SkillResponse.from_skill(skill) for skill in skills],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
        has_next=(pagination.offset + pagination.page_size) < total,
    )


@router.get(
    "/{skill_id}",
    response_model=SkillResponse,
    dependencies=[
        enforced_in_handler(
            "the PDP decides for a tenant row; a catalog projection is platform data"
        )
    ],
)
async def get_skill(
    skill_id: UUID,
    skill_service: SkillServiceDep,
    user_context: UserContextDep,
):
    """Get a skill by ID (tenant or catalog)."""
    skill = await skill_service.get_with_catalog(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    if not getattr(skill, "is_catalog", False):
        # A tenant row; the catalog projection beside it is platform data and
        # carries no ownership tuples to check.
        await require_permission("read", "skill", str(skill_id), user_context.user_id)
        await skill_service.annotate_installs([skill])
    return SkillResponse.from_skill(skill)


@router.post(
    "/update-all",
    response_model=SkillUpdateAllResponse,
    dependencies=[requires_workspace_admin()],
)
async def update_all_skills(skill_service: SkillServiceDep):
    """Update every installed catalog skill that has an update and was not edited here."""
    results = await skill_service.update_all_from_catalog()
    return SkillUpdateAllResponse(
        results=[SkillUpdateResultResponse.from_result(r) for r in results]
    )


@router.post(
    "/{skill_id}/update",
    response_model=SkillResponse,
    dependencies=[requires_workspace_admin()],
)
async def update_installed_skill(
    skill_id: UUID,
    skill_service: SkillServiceDep,
    discard_changes: bool = Query(
        False, description="Update a skill edited in this workspace, discarding the edit"
    ),
):
    """Move an installed catalog skill to its catalog item's current version."""
    with _catalog_fetch_errors():
        result = await skill_service.update_from_catalog(skill_id, discard_changes=discard_changes)
    if result.skill is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    return SkillResponse.from_skill(result.skill)


@router.get(
    "/{skill_id}/versions",
    response_model=list[SkillVersionResponse],
    dependencies=[requires("read", "skill", id_param="skill_id")],
)
async def list_skill_versions(skill_id: UUID, skill_service: SkillServiceDep):
    """Every package the skill pointed at, oldest first; the last is the current one."""
    try:
        skill = await skill_service.get(skill_id)
        versions = await skill_service.list_versions(skill_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail="Skill not found") from e
    current = skill.s3_path if skill else None
    return [
        SkillVersionResponse.from_version(
            v, current=i == len(versions) - 1 and v.s3_path == current
        )
        for i, v in enumerate(versions)
    ]


@router.post(
    "/{skill_id}/versions/{version_id}/rollback",
    response_model=SkillResponse,
    dependencies=[requires("edit", "skill", id_param="skill_id")],
)
async def rollback_skill(skill_id: UUID, version_id: UUID, skill_service: SkillServiceDep):
    """Point the skill at the package one of its versions had; recorded as a new version."""
    try:
        skill = await skill_service.rollback(skill_id, version_id)
    except SkillVersionNotFoundError as e:
        raise HTTPException(status_code=404, detail="Skill version not found") from e
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail="Skill not found") from e
    return SkillResponse.from_skill(skill)


@router.post(
    "/{skill_id}/install",
    response_model=SkillResponse,
    dependencies=[
        unrestricted("workspace member; the workspace-scoped repository is the boundary")
    ],
)
async def install_skill(
    skill_id: UUID,
    skill_service: SkillServiceDep,
):
    """Add a built-in catalog skill to the workspace: fetch its package and pin it.

    A policy rule refusing the item's registry answers 403.
    """
    with _catalog_fetch_errors():
        skill = await skill_service.install_catalog_skill(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")

    # The id may already be a tenant skill, or this workspace's earlier fork.
    # Only the member who created the row is re-granted: a fresh fork was granted
    # by the repository, and this repairs a grant that failed after it committed.
    if str(skill.created_by) == str(skill_service.user_context.user_id):
        await grant_resource_owner(
            resource_id=skill.id,
            workspace_id=skill_service.user_context.workspace_id,
            user_id=skill_service.user_context.user_id,
        )
    return SkillResponse.from_skill(skill)


@router.get(
    "/{skill_id}/content",
    response_model=SkillContentResponse,
    dependencies=[
        unrestricted("workspace member; the workspace-scoped repository is the boundary")
    ],
)
async def get_skill_content(
    skill_id: UUID,
    skill_service: SkillServiceDep,
):
    """Get the main markdown content of a skill (tenant or catalog)."""
    skill = await skill_service.get_with_catalog(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")

    with _source_errors():
        content = await skill_service.read_skill_md(skill)
    return SkillContentResponse(id=str(skill.id), name=skill.name, content=content)


@router.get(
    "/{skill_id}/files",
    response_model=SkillFilesResponse,
    dependencies=[
        unrestricted("workspace member; the workspace-scoped repository is the boundary")
    ],
)
async def list_skill_files(
    skill_id: UUID,
    skill_service: SkillServiceDep,
    include_urls: bool = False,
):
    """List all files in a skill package."""
    try:
        with _source_errors():
            files = await skill_service.get_skill_files(skill_id, include_urls=include_urls)
        return SkillFilesResponse(
            skill_id=str(skill_id),
            files=[SkillFileResponse(path=f.path, size=f.size, url=f.url) for f in files],
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get(
    "/{skill_id}/files/{path:path}",
    dependencies=[
        unrestricted("workspace member; the workspace-scoped repository is the boundary")
    ],
)
async def get_skill_file(
    skill_id: UUID,
    path: str,
    skill_service: SkillServiceDep,
    redirect: bool = True,
):
    """Get a file from a skill package.

    By default, returns a redirect to a presigned URL.
    Set redirect=false to get the presigned URL in the response body.
    """
    try:
        with _source_errors():
            url = await skill_service.get_skill_file_url(skill_id, path)

        if redirect:
            return RedirectResponse(url=url)

        return {"url": url}

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.put(
    "/{skill_id}",
    response_model=SkillResponse,
    dependencies=[
        enforced_in_handler("per-object permission resolved by the PDP once the object is loaded")
    ],
)
async def update_skill(
    skill_id: UUID,
    request: SkillUpdateRequest,
    skill_service: SkillServiceDep,
    user_context: UserContextDep,
):
    """Update a skill."""
    await require_permission("edit", "skill", str(skill_id), user_context.user_id)

    # Build metadata patch with PATCH semantics (only fields the client sent).
    metadata_patch_fields = request.model_dump(
        exclude_unset=True,
        include={"name", "description"},
    )
    metadata_payload = SkillEditMetadata.model_validate(metadata_patch_fields)

    skill = await skill_service.update(skill_id, metadata_payload)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")

    if request.content is not None:
        skill = await skill_service.set_content(skill.id, request.content)
        if not skill:
            raise HTTPException(status_code=404, detail="Skill not found")

    return SkillResponse.from_skill(skill)


@router.delete(
    "/{skill_id}",
    dependencies=[
        enforced_in_handler("per-object permission resolved by the PDP once the object is loaded")
    ],
)
async def delete_skill(
    skill_id: UUID,
    skill_service: SkillServiceDep,
    user_context: UserContextDep,
):
    """Delete a skill."""
    await require_permission("delete", "skill", str(skill_id), user_context.user_id)
    deleted = await skill_service.delete(skill_id)

    if not deleted:
        raise HTTPException(status_code=404, detail="Skill not found")

    return {"status": "deleted", "id": str(skill_id)}


# ============================================================================
# Skill member endpoints (skill-as-bundle)
# ============================================================================


@router.post(
    "/{skill_id}/members",
    response_model=SkillMemberResponse,
    dependencies=[requires("edit", "skill", id_param="skill_id")],
)
async def add_skill_member(
    skill_id: UUID,
    request: SkillMemberAddRequest,
    skill_service: SkillServiceDep,
):
    """Add a child skill to a parent skill bundle."""
    try:
        member = await skill_service.add_member(
            parent_skill_id=skill_id,
            child_skill_id=request.child_skill_id,
            order=request.order,
            is_required=request.is_required,
            dependencies=request.dependencies,
        )
        return SkillMemberResponse(
            parent_skill_id=str(member.parent_skill_id),
            child_skill_id=str(member.child_skill_id),
            order=member.order,
            is_required=member.is_required,
            dependencies=member.dependencies,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get(
    "/{skill_id}/members",
    response_model=list[SkillMemberResponse],
    dependencies=[
        unrestricted("workspace member; the workspace-scoped repository is the boundary")
    ],
)
async def list_skill_members(
    skill_id: UUID,
    skill_service: SkillServiceDep,
):
    """List all child skills of a parent skill bundle."""
    members = await skill_service.get_members(skill_id)
    return [
        SkillMemberResponse(
            parent_skill_id=str(m.parent_skill_id),
            child_skill_id=str(m.child_skill_id),
            order=m.order,
            is_required=m.is_required,
            dependencies=m.dependencies,
        )
        for m in members
    ]


@router.delete(
    "/{skill_id}/members/{child_skill_id}",
    dependencies=[requires("edit", "skill", id_param="skill_id")],
)
async def remove_skill_member(
    skill_id: UUID,
    child_skill_id: UUID,
    skill_service: SkillServiceDep,
):
    """Remove a child skill from a parent skill bundle."""
    removed = await skill_service.remove_member(skill_id, child_skill_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Member association not found")
    return {
        "status": "removed",
        "parent_skill_id": str(skill_id),
        "child_skill_id": str(child_skill_id),
    }


@router.get(
    "/{skill_id}/flatten",
    response_model=list[str],
    dependencies=[
        unrestricted("workspace member; the workspace-scoped repository is the boundary")
    ],
)
async def flatten_skill_members(
    skill_id: UUID,
    skill_service: SkillServiceDep,
):
    """Return child skill IDs in topological execution order."""
    try:
        ordered_ids = await skill_service.flatten(skill_id)
        return [str(sid) for sid in ordered_ids]
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
