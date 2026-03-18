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

    async def get_by_workspace_id(
        self, workspace_id: str, limit: int = 100, offset: int = 0
    ) -> list[ModelInstance]:
        """Get model instances by workspace ID with pagination.

        Note: This method is deprecated. Use list_instances() instead which automatically
        filters by the current workspace from user context.
        """
        # For backward compatibility, but this should be replaced with list_instances()
        if workspace_id != self.user_context.workspace_id:
            return []  # Don't allow cross-workspace access

        return await self.list_instances(limit=limit, offset=offset)

    async def create_instance(self, entity: ModelInstance) -> ModelInstance:
        """Create a new model instance from domain entity.

        Note: This method is deprecated. Use create() with field parameters instead.
        """
        # Extract fields from the instance entity
        instance_data = {
            "id": entity.id,
            "provider_config_id": entity.provider_config_id,
            "model_spec_id": entity.model_spec_id,
            "name": entity.name,
            "description": entity.description,
            "is_active": entity.is_active,
            "is_public": entity.is_public,
            "created_at": entity.created_at,
            "updated_at": entity.updated_at,
        }

        # Remove None values and system fields that will be auto-populated
        instance_data = {k: v for k, v in instance_data.items() if v is not None}
        instance_data.pop("created_at", None)
        instance_data.pop("updated_at", None)

        created_instance = await self.create(**instance_data)
        return await self.get_with_relations(created_instance.id) or created_instance

    async def update_instance(self, entity: ModelInstance) -> ModelInstance:
        """Update an existing model instance from domain entity.

        Note: This method is deprecated. Use update() with field parameters instead.
        """
        # Extract fields from the instance entity
        instance_data = {
            "provider_config_id": entity.provider_config_id,
            "model_spec_id": entity.model_spec_id,
            "name": entity.name,
            "description": entity.description,
            "is_active": entity.is_active,
            "is_public": entity.is_public,
        }

        # Remove None values
        instance_data = {k: v for k, v in instance_data.items() if v is not None}

        updated_instance = await self.update(entity.id, **instance_data)
        return updated_instance or entity
