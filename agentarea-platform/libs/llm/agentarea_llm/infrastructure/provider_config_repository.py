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
