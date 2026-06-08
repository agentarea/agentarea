"""Application service for skill collection management."""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from agentarea_common.base.repository_factory import RepositoryFactory
from agentarea_common.utils.slug import generate_slug

from agentarea_agents.domain.collection_models import SkillCollection
from agentarea_agents.infrastructure.collection_repository import (
    SkillCollectionRepository,
)


@dataclass(frozen=True)
class CollectionSummary:
    """Read model for a collection with its skill count."""

    collection: SkillCollection
    skill_count: int


class SkillCollectionService:
    """Coordinates collection persistence and skill membership."""

    def __init__(self, repository_factory: RepositoryFactory):
        self.repository_factory = repository_factory
        self._repository = repository_factory.create_repository(SkillCollectionRepository)

    async def _resolve_unique_slug(self, name: str) -> str:
        """Generate a workspace-unique slug from ``name``."""
        base = generate_slug(name)
        if await self._repository.get_by_slug(base) is None:
            return base
        for suffix in range(2, 1000):
            candidate = f"{base}-{suffix}"
            if await self._repository.get_by_slug(candidate) is None:
                return candidate
        raise ValueError(f"Exhausted collision suffixes (-2..-999) for slug base '{base}'")

    async def list_collections(self) -> list[CollectionSummary]:
        """List collections in the current workspace with their skill counts."""
        collections = await self._repository.list_all()
        counts = await self._repository.skill_counts()
        return [
            CollectionSummary(collection=c, skill_count=counts.get(str(c.id), 0))
            for c in collections
        ]

    async def create(self, name: str, description: str | None = None) -> SkillCollection:
        """Create a new collection in the current workspace."""
        slug = await self._resolve_unique_slug(name)
        return await self._repository.create(name=name, slug=slug, description=description)

    async def get(self, collection_id: UUID | str) -> SkillCollection | None:
        """Get a collection with its skills loaded."""
        return await self._repository.get_with_skills(collection_id)

    async def update(
        self,
        collection_id: UUID | str,
        name: str | None = None,
        description: str | None = None,
    ) -> SkillCollection | None:
        """Update a collection's name and/or description.

        The slug is immutable once derived at creation and is not re-derived.
        """
        updates: dict[str, Any] = {}
        if name is not None:
            updates["name"] = name
        if description is not None:
            updates["description"] = description
        if not updates:
            return await self._repository.get_by_id(collection_id)
        return await self._repository.update(collection_id, **updates)

    async def delete(self, collection_id: UUID | str) -> bool:
        """Delete a collection from the current workspace."""
        return await self._repository.delete(collection_id)

    async def add_skill(self, collection_id: UUID, skill_id: UUID) -> None:
        """Add a skill to a collection."""
        await self._repository.add_skill(collection_id, skill_id)

    async def remove_skill(self, collection_id: UUID, skill_id: UUID) -> None:
        """Remove a skill from a collection."""
        await self._repository.remove_skill(collection_id, skill_id)
