from uuid import UUID

from agentarea_common.auth.context import UserContext
from agentarea_common.base.workspace_scoped_repository import WorkspaceScopedRepository
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from agentarea_llm.domain.models import ModelSpec, ProviderSpec
from agentarea_llm.infrastructure.catalog_model_spec_repository import (
    CatalogModelSpecItem,
    CatalogModelSpecRepository,
)


def _project_catalog_model_spec(item: CatalogModelSpecItem) -> ModelSpec:
    """Project a catalog model spec item into a transient, read-only ``ModelSpec``.

    The projected spec is NOT persisted. Its ``id`` is the catalog item's id so
    read paths can resolve it back to the registry item. Unlike agents/skills
    there is no copy-on-write: built-in model specs are reference specs that
    users instantiate via ``model_instances``, not fork.

    ``provider_spec`` is attached as a lightweight transient ``ProviderSpec`` (so
    ``ModelSpecResponse.from_domain`` can read provider_name / provider_key)
    using the DB provider_spec_id resolved by the catalog repository.
    """
    spec = item.spec or {}

    model = ModelSpec(
        model_name=spec.get("model_name") or item.name,
        display_name=item.name,
        description=item.description if item.description is not None else spec.get("description"),
        context_window=spec.get("context_window", 4096),
        max_output_tokens=spec.get("max_output_tokens"),
        input_cost_per_token=spec.get("input_cost_per_token"),
        output_cost_per_token=spec.get("output_cost_per_token"),
        supports_function_calling=spec.get("supports_function_calling", False),
        is_active=spec.get("is_active", True),
    )
    model.id = UUID(item.id)
    # Transient projection is never persisted, so DB-default timestamps never
    # fire (they run on INSERT). Carry the registry item's own non-null
    # timestamps so the response schema's required datetimes are populated.
    model.created_at = item.created_at
    model.updated_at = item.updated_at
    if item.provider_spec_id is not None:
        model.provider_spec_id = UUID(item.provider_spec_id)  # type: ignore[assignment]
    model.registry_item_id = item.id  # type: ignore[attr-defined]
    model.is_catalog = True  # type: ignore[attr-defined]
    # Attach a transient provider_spec for the API projection (provider_name /
    # provider_key). provider_specs remain real DB rows in this change.
    if item.provider_key is not None:
        provider = ProviderSpec(
            provider_key=item.provider_key,
            name=item.provider_name or item.provider_key,
            provider_type=item.provider_key,
        )
        if item.provider_spec_id is not None:
            provider.id = UUID(item.provider_spec_id)
        model.provider_spec = provider
    return model


class ModelSpecRepository(WorkspaceScopedRepository[ModelSpec]):
    def __init__(self, session: AsyncSession, user_context: UserContext):
        super().__init__(session, ModelSpec, user_context)

    def _get_catalog_repository(self) -> CatalogModelSpecRepository:
        """Get the read-only catalog (registry_items) repository for model specs."""
        return CatalogModelSpecRepository(session=self.session, user_context=self.user_context)

    async def get_with_relations(self, id: UUID) -> ModelSpec | None:
        """Get model spec by ID with relationships loaded."""
        spec = await self.get_by_id(id)
        if not spec:
            # Fall back to a read-only catalog projection: built-in specs live
            # in the registry catalog only (ADR-003) and are not in model_specs.
            item = await self._get_catalog_repository().get_item(str(id))
            return _project_catalog_model_spec(item) if item else None

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

        specs = await self.list_all(creator_scoped=creator_scoped, **filters)

        # Load relationships for each tenant spec
        spec_ids = [spec.id for spec in specs]
        if spec_ids:
            result = await self.session.execute(
                select(ModelSpec)
                .options(joinedload(ModelSpec.provider_spec), joinedload(ModelSpec.model_instances))
                .where(ModelSpec.id.in_(spec_ids))
            )
            tenant_specs = list(result.unique().scalars().all())
        else:
            tenant_specs = list(specs)

        # Merge read-only catalog projections (built-in specs live in the
        # registry catalog only, ADR-003). A catalog item already instantiated
        # by a tenant row carrying its registry_item_id is shadowed by that row.
        projections = await self._catalog_projections(
            tenant_specs, provider_spec_id=provider_spec_id, is_active=is_active
        )

        merged = [*tenant_specs, *projections]
        if offset:
            merged = merged[offset:]
        if limit:
            merged = merged[:limit]
        return merged

    async def _catalog_projections(
        self,
        tenant_specs: list[ModelSpec],
        *,
        provider_spec_id: UUID | None,
        is_active: bool | None,
    ) -> list[ModelSpec]:
        """Project un-instantiated catalog model spec items as read-only specs."""
        catalog_items = await self._get_catalog_repository().list_items()
        shadowed = {
            str(getattr(s, "registry_item_id", None))
            for s in tenant_specs
            if getattr(s, "registry_item_id", None)
        }
        projections: list[ModelSpec] = []
        for item in catalog_items:
            if item.id in shadowed:
                continue
            spec = _project_catalog_model_spec(item)
            if provider_spec_id is not None and str(spec.provider_spec_id) != str(provider_spec_id):
                continue
            if is_active is not None and spec.is_active != is_active:
                continue
            projections.append(spec)
        return projections

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
