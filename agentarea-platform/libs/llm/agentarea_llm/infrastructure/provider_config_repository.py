from uuid import UUID

from agentarea_common.auth.context import UserContext
from agentarea_common.base.workspace_scoped_repository import WorkspaceScopedRepository
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from agentarea_llm.domain.models import ProviderConfig


class ProviderConfigRepository(WorkspaceScopedRepository[ProviderConfig]):
    def __init__(self, session: AsyncSession, user_context: UserContext):
        super().__init__(session, ProviderConfig, user_context)

    async def get_with_relations(self, id: UUID) -> ProviderConfig | None:
        """Get provider config by ID with relationships loaded."""
        config = await self.get_by_id(id)
        if not config:
            return None

        # Reload with relationships
        result = await self.session.execute(
            select(ProviderConfig)
            .options(
                joinedload(ProviderConfig.provider_spec),
                selectinload(ProviderConfig.model_instances),
            )
            .where(ProviderConfig.id == id)
        )
        return result.scalar_one_or_none()

    async def list_configs(
        self,
        provider_spec_id: UUID | None = None,
        is_active: bool | None = None,
        is_public: bool | None = None,
        limit: int = 100,
        offset: int = 0,
        creator_scoped: bool = False,
    ) -> list[ProviderConfig]:
        """List provider configs with filtering and relationships."""
        filters = {}
        if provider_spec_id is not None:
            filters["provider_spec_id"] = provider_spec_id
        if is_active is not None:
            filters["is_active"] = is_active
        if is_public is not None:
            filters["is_public"] = is_public

        configs = await self.list_all(
            creator_scoped=creator_scoped, limit=limit, offset=offset, **filters
        )

        # Load relationships for each config
        config_ids = [config.id for config in configs]
        if config_ids:
            result = await self.session.execute(
                select(ProviderConfig)
                .options(
                    joinedload(ProviderConfig.provider_spec),
                    selectinload(ProviderConfig.model_instances),
                )
                .where(ProviderConfig.id.in_(config_ids))
            )
            configs_with_relations = result.scalars().all()
            return list(configs_with_relations)

        return configs

    async def get_by_workspace_id(
        self, workspace_id: str, limit: int = 100, offset: int = 0
    ) -> list[ProviderConfig]:
        """Get provider configs by workspace ID with pagination.

        Note: This method is deprecated. Use list_configs() instead which automatically
        filters by the current workspace from user context.
        """
        # For backward compatibility, but this should be replaced with list_configs()
        if workspace_id != self.user_context.workspace_id:
            return []  # Don't allow cross-workspace access

        return await self.list_configs(limit=limit, offset=offset)

    async def create_config(self, entity: ProviderConfig) -> ProviderConfig:
        """Create a new provider config from domain entity.

        Note: This method is deprecated. Use create() with field parameters instead.
        """
        # Extract fields from the config entity
        config_data = {
            "id": entity.id,
            "provider_spec_id": entity.provider_spec_id,
            "name": entity.name,
            "description": entity.description,
            "is_active": entity.is_active,
            "is_public": entity.is_public,
            "api_key": entity.api_key,
            "created_at": entity.created_at,
            "updated_at": entity.updated_at,
        }

        # Remove None values and system fields that will be auto-populated
        config_data = {k: v for k, v in config_data.items() if v is not None}
        config_data.pop("created_at", None)
        config_data.pop("updated_at", None)

        created_config = await self.create(**config_data)
        return await self.get_with_relations(created_config.id) or created_config

    async def update_config(self, entity: ProviderConfig) -> ProviderConfig:
        """Update an existing provider config from domain entity.

        Note: This method is deprecated. Use update() with field parameters instead.
        """
        # Extract fields from the config entity
        config_data = {
            "provider_spec_id": entity.provider_spec_id,
            "name": entity.name,
            "description": entity.description,
            "is_active": entity.is_active,
            "is_public": entity.is_public,
        }

        # Remove None values
        config_data = {k: v for k, v in config_data.items() if v is not None}

        updated_config = await self.update(entity.id, **config_data)
        if updated_config:
            return await self.get_with_relations(updated_config.id)
        return entity
