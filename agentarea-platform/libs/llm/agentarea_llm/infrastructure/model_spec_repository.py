from uuid import UUID

from agentarea_common.auth.context import UserContext
from agentarea_common.base.workspace_scoped_repository import WorkspaceScopedRepository
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from agentarea_llm.domain.models import ModelSpec


class ModelSpecRepository(WorkspaceScopedRepository[ModelSpec]):
    def __init__(self, session: AsyncSession, user_context: UserContext):
        super().__init__(session, ModelSpec, user_context)

    async def get_with_relations(self, id: UUID) -> ModelSpec | None:
        """Get model spec by ID with relationships loaded."""
        spec = await self.get_by_id(id)
        if not spec:
            return None

        # Reload with relationships
        result = await self.session.execute(
            select(ModelSpec)
            .options(joinedload(ModelSpec.provider_spec), joinedload(ModelSpec.model_instances))
            .where(ModelSpec.id == id)
        )
        return result.unique().scalar_one_or_none()

    async def get_by_provider_and_model(
        self, provider_spec_id: UUID, model_name: str
    ) -> ModelSpec | None:
        """Get model spec by provider and model name"""
        spec = await self.find_one_by(provider_spec_id=provider_spec_id, model_name=model_name)
        if not spec:
            return None

        # Reload with relationships
        result = await self.session.execute(
            select(ModelSpec)
            .options(joinedload(ModelSpec.provider_spec), joinedload(ModelSpec.model_instances))
            .where(ModelSpec.id == spec.id)
        )
        return result.unique().scalar_one_or_none()

    async def list_specs(
        self,
        provider_spec_id: UUID | None = None,
        is_active: bool | None = None,
        limit: int = 100,
        offset: int = 0,
        creator_scoped: bool = False,
    ) -> list[ModelSpec]:
        """List model specs with filtering and relationships."""
        filters = {}
        if provider_spec_id is not None:
            filters["provider_spec_id"] = provider_spec_id
        if is_active is not None:
            filters["is_active"] = is_active

        specs = await self.list_all(
            creator_scoped=creator_scoped, limit=limit, offset=offset, **filters
        )

        # Load relationships for each spec
        spec_ids = [spec.id for spec in specs]
        if spec_ids:
            result = await self.session.execute(
                select(ModelSpec)
                .options(joinedload(ModelSpec.provider_spec), joinedload(ModelSpec.model_instances))
                .where(ModelSpec.id.in_(spec_ids))
            )
            specs_with_relations = result.unique().scalars().all()
            return list(specs_with_relations)

        return specs

    async def upsert_by_provider_and_model_kwargs(self, **kwargs) -> ModelSpec:
        """Upsert model spec by provider and model name using kwargs (avoids entity construction)."""
        provider_spec_id = kwargs.get("provider_spec_id")
        model_name = kwargs.get("model_name")
        existing = await self.find_one_by(provider_spec_id=provider_spec_id, model_name=model_name)
        if existing:
            update_fields = {
                k: v
                for k, v in kwargs.items()
                if k not in ("provider_spec_id", "model_name") and v is not None
            }
            updated = await self.update(existing.id, **update_fields)
            return updated or existing
        else:
            return await self.create(**kwargs)

    async def upsert_by_provider_and_model(self, entity: ModelSpec) -> ModelSpec:
        """Upsert model spec by provider and model name - used in bootstrap"""
        existing = await self.get_by_provider_and_model(
            UUID(str(entity.provider_spec_id)), entity.model_name
        )
        if existing:
            # Update existing using kwargs-based update
            updated = await self.update(
                existing.id,
                display_name=entity.display_name,
                description=entity.description,
                context_window=entity.context_window,
                is_active=entity.is_active,
            )
            return updated or existing
        spec_data = {
            "id": entity.id,
            "provider_spec_id": entity.provider_spec_id,
            "model_name": entity.model_name,
            "display_name": entity.display_name,
            "description": entity.description,
            "context_window": entity.context_window,
            "is_active": entity.is_active,
        }
        spec_data = {k: v for k, v in spec_data.items() if v is not None}
        created_spec = await self.create(**spec_data)
        return await self.get_with_relations(created_spec.id) or created_spec
