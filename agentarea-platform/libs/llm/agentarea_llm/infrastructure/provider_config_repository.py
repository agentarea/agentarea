from uuid import UUID

from agentarea_common.auth.context import UserContext
from agentarea_common.base.workspace_scoped_repository import WorkspaceScopedRepository
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from agentarea_llm.domain.models import MANAGED_BY_PLATFORM, ProviderConfig


class ProviderConfigRepository(WorkspaceScopedRepository[ProviderConfig]):
    def __init__(self, session: AsyncSession, user_context: UserContext):
        super().__init__(session, ProviderConfig, user_context)

    def _get_workspace_filter(self):
        """Read the active workspace's configurations, plus the platform's.

        A platform-managed configuration is credentials the deployment operator
        supplies to everyone, so it has to be readable from every workspace. It
        physically lives in whichever workspace the seeder ran under, which no
        tenant can name — a strict workspace filter therefore hides it from all of
        them, which is the same as it not existing.

        This overrides the base filter rather than widening it. ADR-003's objection
        is to the *generic* filter growing an OR-branch for built-in content, which
        would silently change the scope of every workspace-scoped table at once;
        here one repository states one exception for one column, and every other
        table keeps the strict rule.

        Writes deliberately do NOT widen with it: ``update`` and ``delete`` below
        re-assert the strict filter. The base class routes reads and writes through
        this one method, so widening it alone would have let any tenant edit or
        delete the platform's configuration — and repoint its key — simply by
        addressing it by ID.
        """
        return or_(
            self._strict_workspace_filter(),
            ProviderConfig.managed_by == MANAGED_BY_PLATFORM,
        )

    def _strict_workspace_filter(self):
        """The unwidened filter: this workspace's own rows and nothing else."""
        return super()._get_workspace_filter()

    async def update(self, id, creator_scoped: bool = False, **kwargs):
        """Update one of this workspace's own configurations.

        A platform-managed row is invisible to this call even though it is visible
        to reads. Returning None (rather than raising) is what the base class does
        for a row in another workspace, and that is what a platform-managed row is
        from the tenant's side: theirs to use, not theirs to change.
        """
        return await self._scoped_write(
            super().update, id, creator_scoped=creator_scoped, **kwargs
        )

    async def delete(self, id, creator_scoped: bool = False) -> bool:
        """Delete one of this workspace's own configurations.

        Returns False for a platform-managed row, matching the base class's answer
        for anything outside the caller's workspace.
        """
        result = await self._scoped_write(super().delete, id, creator_scoped=creator_scoped)
        return bool(result)

    async def _scoped_write(self, op, id, **kwargs):
        """Run ``op`` only if ``id`` is not a platform-managed row.

        Checked with its own query against the strict filter rather than by reading
        the row through the widened one: the point is to answer "is this the
        caller's to write", and the widened read cannot distinguish that.
        """
        owned = await self.session.execute(
            select(ProviderConfig.id).where(
                ProviderConfig.id == id,
                self._strict_workspace_filter(),
            )
        )
        if owned.scalar_one_or_none() is None:
            return None
        return await op(id, **kwargs)

    async def create_config(self, config: ProviderConfig) -> ProviderConfig:
        """Create a provider config from a domain object.

        Always overwrites ``workspace_id`` and ``created_by`` from the caller's
        ``UserContext`` so an attacker-controlled or stale domain object cannot
        smuggle a write into another workspace or impersonate another user.
        """
        config.workspace_id = self.user_context.workspace_id
        config.created_by = self.user_context.user_id

        self.session.add(config)
        await self.session.commit()
        return await self.get_with_relations(config.id) or config

    async def update_config(self, config: ProviderConfig) -> ProviderConfig:
        """Persist mutations on ``config`` and return the refreshed record.

        Delegates to ``WorkspaceScopedRepository.update_from_entity`` which
        scrubs immutable audit columns and applies the patch within workspace
        scope, then reloads the row with relationships eagerly loaded so the
        caller can serialize ``provider_spec`` / ``model_instances`` without
        triggering async lazy-load.
        """
        updated = await self.update_from_entity(config)
        return await self.get_with_relations(updated.id) or updated

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
