from uuid import UUID

from agentarea_common.auth.context import UserContext
from agentarea_common.base.workspace_scoped_repository import WorkspaceScopedRepository
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from agentarea_llm.domain.models import ModelInstance, ProviderConfig


class ModelInstanceRepository(WorkspaceScopedRepository[ModelInstance]):
    def __init__(self, session: AsyncSession, user_context: UserContext):
        super().__init__(session, ModelInstance, user_context)

    async def create_instance(self, instance: ModelInstance) -> ModelInstance:
        """Create a model instance from a domain object."""
        instance.workspace_id = self.user_context.workspace_id
        if not instance.created_by:
            instance.created_by = self.user_context.user_id

        self.session.add(instance)
        await self.session.commit()
        return await self.get_with_relations(instance.id) or instance

    async def get_with_relations(self, id: UUID) -> ModelInstance | None:
        """Get model instance by ID with relationships loaded."""
        instance = await self.get_by_id(id)
        if not instance:
            return None

        # Reload with relationships
        result = await self.session.execute(
            select(ModelInstance)
            .options(
                joinedload(ModelInstance.provider_config).joinedload(ProviderConfig.provider_spec),
                joinedload(ModelInstance.model_spec),
            )
            .where(ModelInstance.id == id)
        )
        return result.scalar_one_or_none()

    async def list_instances(
        self,
        provider_config_id: UUID | None = None,
        model_spec_id: UUID | None = None,
        is_active: bool | None = None,
        is_public: bool | None = None,
        limit: int = 100,
        offset: int = 0,
        creator_scoped: bool = False,
    ) -> list[ModelInstance]:
        """List model instances with filtering and relationships."""
        filters = {}
        if provider_config_id is not None:
            filters["provider_config_id"] = provider_config_id
        if model_spec_id is not None:
            filters["model_spec_id"] = model_spec_id
        if is_active is not None:
            filters["is_active"] = is_active
        if is_public is not None:
            filters["is_public"] = is_public

        instances = await self.list_all(
            creator_scoped=creator_scoped, limit=limit, offset=offset, **filters
        )

        # Load relationships for each instance
        instance_ids = [instance.id for instance in instances]
        if instance_ids:
            result = await self.session.execute(
                select(ModelInstance)
                .options(
                    joinedload(ModelInstance.provider_config).joinedload(
                        ProviderConfig.provider_spec
                    ),
                    joinedload(ModelInstance.model_spec),
                )
                .where(ModelInstance.id.in_(instance_ids))
            )
            instances_with_relations = result.scalars().all()
            return list(instances_with_relations)

        return instances
