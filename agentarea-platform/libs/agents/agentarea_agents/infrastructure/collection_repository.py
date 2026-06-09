"""Skill collection repository for database operations."""

from datetime import datetime
from uuid import UUID

from agentarea_common.auth.context import UserContext
from agentarea_common.base.workspace_scoped_repository import WorkspaceScopedRepository
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from agentarea_agents.domain.collection_models import (
    SkillCollection,
    collection_skills_table,
)


class SkillCollectionRepository(WorkspaceScopedRepository[SkillCollection]):
    """Repository for SkillCollection CRUD and membership operations."""

    def __init__(self, session: AsyncSession, user_context: UserContext):
        super().__init__(session, SkillCollection, user_context)

    async def get_by_slug(self, slug: str) -> SkillCollection | None:
        """Get a collection by workspace-scoped slug."""
        query = select(self.model_class).where(
            self.model_class.slug == slug,
            self._get_workspace_filter(),
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_with_skills(self, collection_id: UUID | str) -> SkillCollection | None:
        """Get a collection with its associated skills loaded."""
        query = (
            select(self.model_class)
            .where(
                self.model_class.id == collection_id,
                self._get_workspace_filter(),
            )
            .options(selectinload(self.model_class.skills))
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def skill_count(self, collection_id: UUID | str) -> int:
        """Count the skills in a collection."""
        query = select(func.count(collection_skills_table.c.skill_id)).where(
            collection_skills_table.c.collection_id == collection_id
        )
        result = await self.session.execute(query)
        return result.scalar() or 0

    async def skill_counts(self) -> dict[str, int]:
        """Return a mapping of collection_id -> skill count for the workspace.

        Only counts memberships whose collection is in the current workspace.
        """
        query = (
            select(
                collection_skills_table.c.collection_id,
                func.count(collection_skills_table.c.skill_id),
            )
            .join(
                self.model_class,
                self.model_class.id == collection_skills_table.c.collection_id,
            )
            .where(self._get_workspace_filter())
            .group_by(collection_skills_table.c.collection_id)
        )
        result = await self.session.execute(query)
        return {str(collection_id): count for collection_id, count in result.all()}

    async def add_skill(self, collection_id: UUID, skill_id: UUID) -> None:
        """Add a skill to a collection (idempotent)."""
        query = select(collection_skills_table).where(
            and_(
                collection_skills_table.c.collection_id == collection_id,
                collection_skills_table.c.skill_id == skill_id,
            )
        )
        result = await self.session.execute(query)
        existing = result.first()

        if existing is None:
            await self.session.execute(
                collection_skills_table.insert().values(
                    collection_id=collection_id,
                    skill_id=skill_id,
                    created_at=datetime.now(),
                )
            )
            await self.session.commit()

    async def remove_skill(self, collection_id: UUID, skill_id: UUID) -> None:
        """Remove a skill from a collection."""
        await self.session.execute(
            collection_skills_table.delete().where(
                and_(
                    collection_skills_table.c.collection_id == collection_id,
                    collection_skills_table.c.skill_id == skill_id,
                )
            )
        )
        await self.session.commit()
