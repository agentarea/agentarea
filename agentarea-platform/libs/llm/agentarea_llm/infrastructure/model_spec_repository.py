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
        return result.scalar_one_or_none()

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
        return result.scalar_one_or_none()

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
            specs_with_relations = result.scalars().all()
            return list(specs_with_relations)

        return specs

    async def create_spec(self, entity: ModelSpec) -> ModelSpec:
        """Create a new model spec from domain entity.

        Note: This method is deprecated. Use create() with field parameters instead.
        """
        # Extract fields from the spec entity
        spec_data = {
            "id": entity.id,
            "provider_spec_id": entity.provider_spec_id,
            "model_name": entity.model_name,
            "display_name": entity.display_name,
            "description": entity.description,
            "context_window": entity.context_window,
            "is_active": entity.is_active,
            "created_at": entity.created_at,
            "updated_at": entity.updated_at,
        }

        # Remove None values and system fields that will be auto-populated
        spec_data = {k: v for k, v in spec_data.items() if v is not None}
        spec_data.pop("created_at", None)
        spec_data.pop("updated_at", None)

        created_spec = await self.create(**spec_data)
        return await self.get_with_relations(created_spec.id) or created_spec

    async def update_spec(self, entity: ModelSpec) -> ModelSpec:
        """Update an existing model spec from domain entity.

        Note: This method is deprecated. Use update() with field parameters instead.
        """
        # Extract fields from the spec entity
        spec_data = {
            "provider_spec_id": entity.provider_spec_id,
            "model_name": entity.model_name,
            "display_name": entity.display_name,
            "description": entity.description,
            "context_window": entity.context_window,
            "is_active": entity.is_active,
        }

        # Remove None values
        spec_data = {k: v for k, v in spec_data.items() if v is not None}

        updated_spec = await self.update(entity.id, **spec_data)
        return updated_spec or entity

    async def upsert_by_provider_and_model(self, entity: ModelSpec) -> ModelSpec:
        """Upsert model spec by provider and model name - used in bootstrap"""
        existing = await self.get_by_provider_and_model(entity.provider_spec_id, entity.model_name)
        if existing:
            # Update existing
            existing.display_name = entity.display_name
            existing.description = entity.description
            existing.context_window = entity.context_window
            existing.is_active = entity.is_active
            return await self.update(existing)
        else:
            # Create new
            return await self.create(entity)
