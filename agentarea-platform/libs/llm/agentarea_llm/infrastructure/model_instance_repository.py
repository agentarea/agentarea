from uuid import UUID

from agentarea_common.auth.context import UserContext
from agentarea_common.base.workspace_scoped_repository import WorkspaceScopedRepository
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from agentarea_llm.domain.models import MANAGED_BY_PLATFORM, ModelInstance, ProviderConfig


class ModelInstanceRepository(WorkspaceScopedRepository[ModelInstance]):
    def __init__(self, session: AsyncSession, user_context: UserContext):
        super().__init__(session, ModelInstance, user_context)

    def _get_workspace_filter(self):
        """Read this workspace's model instances, plus the platform's.

        An instance is the platform's exactly when its provider configuration is —
        the configuration is where the credentials live, so it is the only place
        that fact belongs. Re-stating it on the instance would be a second copy of
        one answer, free to drift from the first.

        Mirrors ProviderConfigRepository: reads widen, writes do not.
        """
        return or_(
            self._strict_workspace_filter(),
            ModelInstance.provider_config_id.in_(
                select(ProviderConfig.id).where(
                    ProviderConfig.managed_by == MANAGED_BY_PLATFORM
                )
            ),
        )

    def _strict_workspace_filter(self):
        """The unwidened filter: this workspace's own rows and nothing else."""
        return super()._get_workspace_filter()

    async def update(self, id, creator_scoped: bool = False, **kwargs):
        """Update one of this workspace's own instances; None for the platform's."""
        return await self._scoped_write(
            super().update, id, creator_scoped=creator_scoped, **kwargs
        )

    async def delete(self, id, creator_scoped: bool = False) -> bool:
        """Delete one of this workspace's own instances; False for the platform's."""
        result = await self._scoped_write(super().delete, id, creator_scoped=creator_scoped)
        return bool(result)

    async def _scoped_write(self, op, id, **kwargs):
        """Run ``op`` only if ``id`` is a row this workspace owns outright."""
        owned = await self.session.execute(
            select(ModelInstance.id).where(
                ModelInstance.id == id,
                self._strict_workspace_filter(),
            )
        )
        if owned.scalar_one_or_none() is None:
            return None
        return await op(id, **kwargs)

    async def create_instance(self, instance: ModelInstance) -> ModelInstance:
        """Create a model instance from a domain object.

        Always overwrites ``workspace_id`` and ``created_by`` from the caller's
        ``UserContext`` so an attacker-controlled or stale domain object cannot
        smuggle a write into another workspace or impersonate another user.
        """
        instance.workspace_id = self.user_context.workspace_id
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
