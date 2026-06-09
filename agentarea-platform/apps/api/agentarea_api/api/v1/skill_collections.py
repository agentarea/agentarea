"""Skill collection CRUD + membership API endpoints.

Collections group skills so that a single ReBAC grant fans out to every
contained skill. Membership changes are mirrored into Ory Keto as
``Skill:<sid>#collections@SkillCollection:<cid>`` tuples when Keto is enabled.
"""

import logging
from typing import Annotated
from uuid import UUID

from agentarea_agents.application.collection_service import SkillCollectionService
from agentarea_agents.infrastructure.collection_repository import SkillCollectionRepository
from agentarea_agents.infrastructure.skill_repository import SkillRepository
from agentarea_common.auth import UserContextDep
from agentarea_common.base.repository_factory import RepositoryFactory
from agentarea_common.infrastructure.database import get_db_session
from agentarea_common.rebac import KetoError, KetoUnavailableError, RelationTuple
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from .rebac import get_keto

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/skill-collections", tags=["skill-collections"])

DatabaseSessionDep = Annotated[AsyncSession, Depends(get_db_session)]


class CollectionCreateRequest(BaseModel):
    name: str
    description: str | None = None


class CollectionUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None


class AddSkillRequest(BaseModel):
    skill_id: UUID


class CollectionSummaryResponse(BaseModel):
    id: str
    name: str
    description: str | None
    skill_count: int


class SkillRef(BaseModel):
    id: str
    name: str


class CollectionDetailResponse(BaseModel):
    id: str
    name: str
    description: str | None
    skills: list[SkillRef]


@router.get("/", response_model=list[CollectionSummaryResponse])
async def list_collections(
    user_context: UserContextDep,
    db_session: DatabaseSessionDep,
) -> list[CollectionSummaryResponse]:
    """List collections in the current workspace with skill counts."""
    service = SkillCollectionService(RepositoryFactory(db_session, user_context))
    summaries = await service.list_collections()
    return [
        CollectionSummaryResponse(
            id=str(s.collection.id),
            name=s.collection.name,
            description=s.collection.description,
            skill_count=s.skill_count,
        )
        for s in summaries
    ]


@router.post("/", response_model=CollectionSummaryResponse, status_code=201)
async def create_collection(
    payload: CollectionCreateRequest,
    user_context: UserContextDep,
    db_session: DatabaseSessionDep,
) -> CollectionSummaryResponse:
    """Create a new collection in the current workspace."""
    service = SkillCollectionService(RepositoryFactory(db_session, user_context))
    collection = await service.create(name=payload.name, description=payload.description)
    return CollectionSummaryResponse(
        id=str(collection.id),
        name=collection.name,
        description=collection.description,
        skill_count=0,
    )


@router.get("/{collection_id}", response_model=CollectionDetailResponse)
async def get_collection(
    collection_id: UUID,
    user_context: UserContextDep,
    db_session: DatabaseSessionDep,
) -> CollectionDetailResponse:
    """Read one collection with its skills."""
    service = SkillCollectionService(RepositoryFactory(db_session, user_context))
    collection = await service.get(collection_id)
    if collection is None:
        raise HTTPException(status_code=404, detail="Collection not found")
    return CollectionDetailResponse(
        id=str(collection.id),
        name=collection.name,
        description=collection.description,
        skills=[SkillRef(id=str(s.id), name=s.name) for s in collection.skills],
    )


@router.put("/{collection_id}", response_model=CollectionSummaryResponse)
async def update_collection(
    collection_id: UUID,
    payload: CollectionUpdateRequest,
    user_context: UserContextDep,
    db_session: DatabaseSessionDep,
) -> CollectionSummaryResponse:
    """Update a collection's name and/or description."""
    factory = RepositoryFactory(db_session, user_context)
    service = SkillCollectionService(factory)
    collection = await service.update(
        collection_id, name=payload.name, description=payload.description
    )
    if collection is None:
        raise HTTPException(status_code=404, detail="Collection not found")
    skill_count = await factory.create_repository(SkillCollectionRepository).skill_count(
        collection_id
    )
    return CollectionSummaryResponse(
        id=str(collection.id),
        name=collection.name,
        description=collection.description,
        skill_count=skill_count,
    )


@router.delete("/{collection_id}", status_code=204)
async def delete_collection(
    collection_id: UUID,
    user_context: UserContextDep,
    db_session: DatabaseSessionDep,
) -> None:
    """Delete a collection from the current workspace."""
    service = SkillCollectionService(RepositoryFactory(db_session, user_context))
    deleted = await service.delete(collection_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Collection not found")


@router.post("/{collection_id}/skills", status_code=204)
async def add_skill_to_collection(
    collection_id: UUID,
    payload: AddSkillRequest,
    user_context: UserContextDep,
    db_session: DatabaseSessionDep,
) -> None:
    """Add a skill to a collection and mirror the membership into Keto."""
    factory = RepositoryFactory(db_session, user_context)
    service = SkillCollectionService(factory)
    if await factory.create_repository(SkillCollectionRepository).get_by_id(collection_id) is None:
        raise HTTPException(status_code=404, detail="Collection not found")
    if await factory.create_repository(SkillRepository).get_by_id(payload.skill_id) is None:
        raise HTTPException(status_code=404, detail="Skill not found")

    # Write Keto first — if Keto is down the DB is not mutated (consistent state).
    keto = get_keto()
    if keto is not None:
        try:
            await keto.write_tuple(
                RelationTuple(
                    namespace="Skill",
                    object=str(payload.skill_id),
                    relation="collections",
                    subject_id=f"SkillCollection:{collection_id}",
                )
            )
        except (KetoError, KetoUnavailableError):
            logger.exception(
                "Failed to write Keto membership tuple for skill=%s collection=%s",
                payload.skill_id,
                collection_id,
            )
            raise HTTPException(
                status_code=503, detail="Keto unavailable; membership tuple not written"
            ) from None
    await service.add_skill(collection_id, payload.skill_id)


@router.delete("/{collection_id}/skills/{skill_id}", status_code=204)
async def remove_skill_from_collection(
    collection_id: UUID,
    skill_id: UUID,
    user_context: UserContextDep,
    db_session: DatabaseSessionDep,
) -> None:
    """Remove a skill from a collection and delete the Keto membership tuple."""
    factory = RepositoryFactory(db_session, user_context)
    service = SkillCollectionService(factory)
    if await factory.create_repository(SkillCollectionRepository).get_by_id(collection_id) is None:
        raise HTTPException(status_code=404, detail="Collection not found")

    # Delete Keto tuple first — if Keto is down the DB is not mutated (grant stays consistent).
    keto = get_keto()
    if keto is not None:
        try:
            await keto.delete_tuple(
                RelationTuple(
                    namespace="Skill",
                    object=str(skill_id),
                    relation="collections",
                    subject_id=f"SkillCollection:{collection_id}",
                )
            )
        except (KetoError, KetoUnavailableError):
            logger.exception(
                "Failed to delete Keto membership tuple for skill=%s collection=%s",
                skill_id,
                collection_id,
            )
            raise HTTPException(
                status_code=503, detail="Keto unavailable; membership tuple not deleted"
            ) from None
    await service.remove_skill(collection_id, skill_id)
