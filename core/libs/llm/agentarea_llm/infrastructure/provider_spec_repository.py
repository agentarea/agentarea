from typing import List
from uuid import UUID

from agentarea_common.base.workspace_scoped_repository import WorkspaceScopedRepository
from agentarea_common.auth.context import UserContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from agentarea_llm.domain.models import ProviderSpec


class ProviderSpecRepository(WorkspaceScopedRepository[ProviderSpec]):
    def __init__(self, session: AsyncSession, user_context: UserContext):
        super().__init__(session, ProviderSpec, user_context)

    async def get_with_relations(self, id: UUID) -> ProviderSpec | None:
        """Get provider spec by ID with relationships loaded."""
        spec = await self.get_by_id(id)
        if not spec:
            return None
        
        # Reload with relationships
        result = await self.session.execute(
            select(ProviderSpec)
            .options(
                selectinload(ProviderSpec.model_specs),
                selectinload(ProviderSpec.provider_configs)
            )
            .where(ProviderSpec.id == id)
        )
        return result.scalar_one_or_none()

    async def get_by_provider_key(self, provider_key: str) -> ProviderSpec | None:
        """Get provider spec by provider_key (e.g., 'openai', 'anthropic')"""
        spec = await self.find_one_by(provider_key=provider_key)
        if not spec:
            return None
        
        # Reload with relationships
        result = await self.session.execute(
            select(ProviderSpec)
            .options(
                selectinload(ProviderSpec.model_specs),
                selectinload(ProviderSpec.provider_configs)
            )
            .where(ProviderSpec.id == spec.id)
        )
        return result.scalar_one_or_none()

    async def list_specs(
        self, 
        is_builtin: bool | None = None, 
        limit: int = 100, 
        offset: int = 0,
        creator_scoped: bool = False
    ) -> List[ProviderSpec]:
        """List provider specs with filtering and relationships."""
        filters = {}
        if is_builtin is not None:
            filters['is_builtin'] = is_builtin

        specs = await self.list_all(
            creator_scoped=creator_scoped,
            limit=limit,
            offset=offset,
            **filters
        )
        
        # Load relationships for each spec
        spec_ids = [spec.id for spec in specs]
        if spec_ids:
            result = await self.session.execute(
                select(ProviderSpec)
                .options(
                    selectinload(ProviderSpec.model_specs),
                    selectinload(ProviderSpec.provider_configs)
                )
                .where(ProviderSpec.id.in_(spec_ids))
            )
            specs_with_relations = result.scalars().all()
            return list(specs_with_relations)
        
        return specs

    async def create_spec(self, entity: ProviderSpec) -> ProviderSpec:
        """Create a new provider spec from domain entity.
        
        Note: This method is deprecated. Use create() with field parameters instead.
        """
        # Extract fields from the spec entity
        spec_data = {
            'id': entity.id,
            'provider_key': entity.provider_key,
            'name': entity.name,
            'description': entity.description,
            'provider_type': entity.provider_type,
            'icon': entity.icon,
            'is_builtin': entity.is_builtin,
            'created_at': entity.created_at,
            'updated_at': entity.updated_at,
        }
        
        # Remove None values and system fields that will be auto-populated
        spec_data = {k: v for k, v in spec_data.items() if v is not None}
        spec_data.pop('created_at', None)
        spec_data.pop('updated_at', None)
        
        created_spec = await self.create(**spec_data)
        return await self.get_with_relations(created_spec.id) or created_spec

    async def update_spec(self, entity: ProviderSpec) -> ProviderSpec:
        """Update an existing provider spec from domain entity.
        
        Note: This method is deprecated. Use update() with field parameters instead.
        """
        # Extract fields from the spec entity
        spec_data = {
            'provider_key': entity.provider_key,
            'name': entity.name,
            'description': entity.description,
            'provider_type': entity.provider_type,
            'icon': entity.icon,
            'is_builtin': entity.is_builtin,
        }
        
        # Remove None values
        spec_data = {k: v for k, v in spec_data.items() if v is not None}
        
        updated_spec = await self.update(entity.id, **spec_data)
        return updated_spec or entity

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
            return await self.create(entity) 