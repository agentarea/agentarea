"""Skills API endpoints for managing agent skills."""

from typing import Annotated
from uuid import UUID

from agentarea_agents.application.skill_service import SkillService
from agentarea_agents.domain.skill_models import Skill
from agentarea_agents.infrastructure.github_skill_importer import (
    GitHubNotFoundError,
    GitHubRateLimitError,
    GitHubSkillImporterError,
)
from agentarea_agents.schemas.skills_dto import (
    SkillCreateFromContent,
    SkillEditMetadata,
    SkillImportFromGithub,
)
from agentarea_common.auth.dependencies import UserContextDep
from agentarea_common.auth.permission import require_permission
from agentarea_common.base import RepositoryFactoryDep
from agentarea_common.base.pagination import PaginatedResponse, PaginationParams
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

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
    name: str | None = Field(None, description="Optional name override")
    description: str | None = Field(None, description="Optional description override")

    def model_post_init(self, __context) -> None:
        """Validate that exactly one source is provided."""
        if not self.content and not self.github_url:
            raise ValueError("Either 'content' or 'github_url' must be provided")
        if self.content and self.github_url:
            raise ValueError("Only one of 'content' or 'github_url' can be provided")


class SkillUpdateRequest(BaseModel):
    """Request to update a skill."""

    name: str | None = Field(None, description="New name")
    description: str | None = Field(None, description="New description")
    content: str | None = Field(None, description="New content (only for content-type skills)")


class SkillResponse(BaseModel):
    """Skill response model."""

    id: str
    name: str
    slug: str
    description: str | None
    source_type: str
    source_url: str | None
    has_files: bool
    network_scope: str
    workspace_id: str
    created_at: str
    updated_at: str
    # Catalog provenance (ADR-003). ``is_catalog`` marks a read-only built-in
    # skill that has not been forked into the workspace yet.
    is_catalog: bool = False
    registry_item_id: str | None = None
    update_available: bool = False

    @classmethod
    def from_skill(cls, skill: Skill) -> "SkillResponse":
        """Create response from Skill entity."""
        network_scope = getattr(skill, "network_scope", "private")
        if not isinstance(network_scope, str):
            network_scope = "private"

        registry_item_id = getattr(skill, "registry_item_id", None)
        return cls(
            id=str(skill.id),
            name=skill.name,
            slug=skill.slug,
            description=skill.description,
            source_type=skill.source_type,
            source_url=skill.source_url,
            has_files=skill.s3_path is not None,
            network_scope=network_scope,
            workspace_id=getattr(skill, "workspace_id", "") or "",
            created_at=skill.created_at.isoformat() if skill.created_at else "",
            updated_at=skill.updated_at.isoformat() if skill.updated_at else "",
            is_catalog=bool(getattr(skill, "is_catalog", False)),
            registry_item_id=str(registry_item_id) if registry_item_id else None,
            update_available=bool(getattr(skill, "update_available", False)),
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
    order: int = Field(0, description="Execution order hint")
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


# ============================================================================
# Endpoints
# ============================================================================


@router.post("", response_model=SkillResponse)
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

        return SkillResponse.from_skill(skill)

    except GitHubRateLimitError as e:
        raise HTTPException(status_code=429, detail=str(e)) from e
    except GitHubNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except GitHubSkillImporterError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/upload", response_model=SkillResponse)
async def upload_skill(
    skill_service: SkillServiceDep,
    file: UploadFile = File(..., description="ZIP file containing the skill package"),
    name: str | None = None,
    description: str | None = None,
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
        return SkillResponse.from_skill(skill)

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("", response_model=PaginatedResponse[SkillResponse])
async def list_skills(
    skill_service: SkillServiceDep,
    pagination: PaginationParams = Depends(),
    source_type: str | None = Query(None, description="Filter by source type"),
    has_files: bool | None = Query(None, description="Filter by package-backed skills"),
    network_scope: str | None = Query(None, description="Filter by network scope"),
    from_registry: bool | None = Query(None, description="Filter registry-created skills"),
):
    """List skills in the workspace."""
    skills, total = await skill_service.list_paginated(
        limit=pagination.limit,
        offset=pagination.offset,
        search=pagination.search,
        source_type=source_type,
        has_files=has_files,
        network_scope=network_scope,
        from_registry=from_registry,
    )
    return PaginatedResponse(
        items=[SkillResponse.from_skill(skill) for skill in skills],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
        has_next=(pagination.offset + pagination.page_size) < total,
    )


@router.get("/{skill_id}", response_model=SkillResponse)
async def get_skill(
    skill_id: UUID,
    skill_service: SkillServiceDep,
):
    """Get a skill by ID (tenant or catalog)."""
    skill = await skill_service.get_with_catalog(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    return SkillResponse.from_skill(skill)


@router.get("/{skill_id}/content", response_model=SkillContentResponse)
async def get_skill_content(
    skill_id: UUID,
    skill_service: SkillServiceDep,
):
    """Get the main markdown content of a skill (tenant or catalog)."""
    skill = await skill_service.get_with_catalog(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")

    return SkillContentResponse(
        id=str(skill.id),
        name=skill.name,
        content=skill.content or "",
    )


@router.get("/{skill_id}/files", response_model=SkillFilesResponse)
async def list_skill_files(
    skill_id: UUID,
    skill_service: SkillServiceDep,
    include_urls: bool = False,
):
    """List all files in a skill package."""
    try:
        files = await skill_service.get_skill_files(skill_id, include_urls=include_urls)
        return SkillFilesResponse(
            skill_id=str(skill_id),
            files=[SkillFileResponse(path=f.path, size=f.size, url=f.url) for f in files],
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/{skill_id}/files/{path:path}")
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
        url = await skill_service.get_skill_file_url(skill_id, path)

        if redirect:
            return RedirectResponse(url=url)

        return {"url": url}

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.put("/{skill_id}", response_model=SkillResponse)
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
        skill = await skill_service.set_content(skill_id, request.content)
        if not skill:
            raise HTTPException(status_code=404, detail="Skill not found")

    return SkillResponse.from_skill(skill)


@router.delete("/{skill_id}")
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


@router.post("/{skill_id}/members", response_model=SkillMemberResponse)
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


@router.get("/{skill_id}/members", response_model=list[SkillMemberResponse])
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


@router.delete("/{skill_id}/members/{child_skill_id}")
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


@router.get("/{skill_id}/flatten", response_model=list[str])
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
