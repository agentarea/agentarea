from uuid import UUID

from agentarea_common.auth.context import UserContext
from agentarea_common.base.repository import BaseRepository
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from agentarea_llm.domain.models import ProviderSpec


class ProviderSpecRepository(BaseRepository[ProviderSpec]):  # Temporarily removed workspace scoping
    def __init__(self, session: AsyncSession, user_context: UserContext | None = None):
        super().__init__(session)
        self.model_class = ProviderSpec
        self.user_context = user_context or UserContext(user_id="system", workspace_id="system")

    def _ensure_scope(self, entity: ProviderSpec) -> ProviderSpec:
        """Populate required audit scope for globally-addressed provider specs."""
        if not getattr(entity, "workspace_id", None):
            entity.workspace_id = self.user_context.workspace_id
        if not getattr(entity, "created_by", None):
            entity.created_by = self.user_context.user_id
        return entity

    async def create(self, entity: ProviderSpec) -> ProviderSpec:
        """Create a provider spec, filling required workspace audit fields."""
        return await super().create(self._ensure_scope(entity))

    async def get_with_relations(self, id: UUID) -> ProviderSpec | None:
        """Get provider spec by ID with relationships loaded."""
        spec = await self.get(id)
        if not spec:
            return None

        # Reload with relationships
        result = await self.session.execute(
            select(ProviderSpec)
            .options(
                selectinload(ProviderSpec.model_specs), selectinload(ProviderSpec.provider_configs)
            )
            .where(ProviderSpec.id == id)
        )
        return result.scalar_one_or_none()

    async def get_by_provider_key(self, provider_key: str) -> ProviderSpec | None:
        """Get provider spec by provider_key (e.g., 'openai', 'anthropic')"""
        result = await self.session.execute(
            select(ProviderSpec).where(ProviderSpec.provider_key == provider_key)
        )
        spec = result.scalar_one_or_none()
        if not spec:
            return None

        # Reload with relationships
        result = await self.session.execute(
            select(ProviderSpec)
            .options(
                selectinload(ProviderSpec.model_specs), selectinload(ProviderSpec.provider_configs)
            )
            .where(ProviderSpec.id == spec.id)
        )
        return result.scalar_one_or_none()

    async def list_specs(
        self,
        is_builtin: bool | None = None,
        limit: int = 100,
        offset: int = 0,
        creator_scoped: bool = False,
    ) -> list[ProviderSpec]:
        """List provider specs with filtering and relationships."""
        filters = {}
        if is_builtin is not None:
            filters["is_builtin"] = is_builtin

        # Build query with filters
        query = select(ProviderSpec)
        if is_builtin is not None:
            query = query.where(ProviderSpec.is_builtin == is_builtin)

        query = query.limit(limit).offset(offset)
        result = await self.session.execute(query)
        specs = list(result.scalars().all())

        # Load relationships for each spec
        spec_ids = [spec.id for spec in specs]
        if spec_ids:
            result = await self.session.execute(
                select(ProviderSpec)
                .options(
                    selectinload(ProviderSpec.model_specs),
                    selectinload(ProviderSpec.provider_configs),
                )
                .where(ProviderSpec.id.in_(spec_ids))
            )
            specs_with_relations = result.scalars().all()
            return list(specs_with_relations)

        return specs

    async def upsert_by_provider_key(self, entity: ProviderSpec) -> ProviderSpec:
        """Upsert provider spec by provider_key - used in bootstrap"""
        existing = await self.get_by_provider_key(entity.provider_key)
        if existing:
            # Update existing
            existing.name = entity.name
            existing.description = entity.description
            existing.provider_type = entity.provider_type
            existing.icon = entity.icon
            existing.is_builtin = entity.is_builtin
            return await self.update(existing)
        else:
            # Create new
            return await self.create(self._ensure_scope(entity))
