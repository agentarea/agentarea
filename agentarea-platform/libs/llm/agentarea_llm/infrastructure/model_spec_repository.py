from uuid import UUID

from agentarea_common.auth.context import UserContext
from agentarea_common.base.workspace_scoped_repository import WorkspaceScopedRepository
from agentarea_common.constants import PLATFORM_WORKSPACE_ID
from agentarea_common.exceptions.errors import AppError
from agentarea_common.money import to_optional_money
from fastapi import status
from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from agentarea_llm.domain.models import ModelSpec, ProviderSpec
from agentarea_llm.infrastructure.catalog_model_spec_repository import (
    CatalogModelSpecItem,
    CatalogModelSpecRepository,
)


class ModelPricingNotConfiguredError(AppError):
    """A catalog model without an input or output price cannot be run, so it cannot be added."""

    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "model_pricing_not_configured"


def _project_catalog_model_spec(item: CatalogModelSpecItem) -> ModelSpec:
    """Project a catalog model spec item into a transient, read-only ``ModelSpec``.

    The projected spec is NOT persisted. Its ``id`` is the catalog item's id so
    read paths can resolve it back to the registry item. Adding it to a
    workspace copies it into that workspace's ``model_specs`` row
    (``get_or_copy_catalog_spec``), which a model instance can reference.

    ``provider_spec`` is attached as a lightweight transient ``ProviderSpec`` (so
    ``ModelSpecResponse.from_domain`` can read provider_name / provider_key)
    using the DB provider_spec_id resolved by the catalog repository.
    """
    spec = item.spec or {}

    model = ModelSpec(
        model_name=spec.get("model_name") or item.name,
        display_name=item.name,
        description=item.description if item.description is not None else spec.get("description"),
        context_window=spec["context_window"],
        max_output_tokens=spec.get("max_output_tokens"),
        input_cost_per_token=to_optional_money(spec.get("input_cost_per_token")),
        output_cost_per_token=to_optional_money(spec.get("output_cost_per_token")),
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


def _model_key(spec: ModelSpec) -> tuple[str, str]:
    return (str(spec.provider_spec_id), spec.model_name)


def _is_priced(spec: ModelSpec) -> bool:
    return spec.input_cost_per_token is not None and spec.output_cost_per_token is not None


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

    async def get_usable(self, id: UUID) -> ModelSpec | None:
        """A spec a model instance in this workspace may point at: its own or the platform's."""
        result = await self.session.execute(
            select(ModelSpec).where(
                ModelSpec.id == id,
                or_(
                    self._get_workspace_filter(),
                    ModelSpec.workspace_id == PLATFORM_WORKSPACE_ID,
                ),
            )
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
        # registry catalog only, ADR-003). A model this workspace already has a
        # row for is shadowed by that row, whatever the filters kept of it.
        projections = await self._catalog_projections(
            await self._own_model_keys(), provider_spec_id=provider_spec_id, is_active=is_active
        )

        merged = [*tenant_specs, *projections]
        if offset:
            merged = merged[offset:]
        if limit:
            merged = merged[:limit]
        return merged

    async def _own_model_keys(self) -> set[tuple[str, str]]:
        result = await self.session.execute(
            select(ModelSpec.provider_spec_id, ModelSpec.model_name).where(
                self._get_workspace_filter()
            )
        )
        return {(str(pid), name) for pid, name in result.all()}

    async def _catalog_projections(
        self,
        shadowed: set[tuple[str, str]],
        *,
        provider_spec_id: UUID | None,
        is_active: bool | None,
    ) -> list[ModelSpec]:
        """Project catalog items as read-only specs, one per ``(provider_spec_id, model_name)``.

        ``shadowed`` holds the keys this workspace already has a row for. The
        same model published by several registries is projected once, from the
        preferred registry, and not at all when that copy has no price: it
        could not be added (``get_or_copy_catalog_spec``) nor run.
        """
        catalog_items = await self._get_catalog_repository().list_items()
        seen = set(shadowed)
        projections: list[ModelSpec] = []
        for item in catalog_items:
            spec = _project_catalog_model_spec(item)
            key = _model_key(spec)
            if key in seen:
                continue
            seen.add(key)
            if not _is_priced(spec):
                continue
            if provider_spec_id is not None and str(spec.provider_spec_id) != str(provider_spec_id):
                continue
            if is_active is not None and spec.is_active != is_active:
                continue
            projections.append(spec)
        projections.sort(key=lambda spec: spec.display_name)
        return projections

    async def get_or_copy_catalog_spec(self, item_id: UUID) -> ModelSpec | None:
        """This workspace's spec for a catalog model, copied from the catalog on first use.

        A model instance references a ``model_specs`` row, never a catalog item.
        A row this workspace already has for the same ``(provider_spec_id,
        model_name)`` is returned untouched: its prices are the workspace's own.
        Otherwise the preferred registry's copy of the model is copied, whichever
        registry's item ``item_id`` names. The copy freezes the catalog price at
        first add, as discovery does; an admin edits the workspace row to change it.

        None when the item is not a catalog model of an active registry or its
        provider is not installed.

        Raises:
            ModelPricingNotConfiguredError: the preferred copy has no input or
                output price, so a run on it could not be billed.
        """
        catalog = self._get_catalog_repository()
        item = await catalog.get_item(str(item_id))
        if item is None or item.provider_spec_id is None:
            return None
        key = _model_key(_project_catalog_model_spec(item))
        provider_spec_id, model_name = UUID(item.provider_spec_id), key[1]
        existing = await self.find_one_by(provider_spec_id=provider_spec_id, model_name=model_name)
        if existing:
            return existing
        preferred = next(
            (
                spec
                for spec in map(_project_catalog_model_spec, await catalog.list_items())
                if _model_key(spec) == key
            ),
            None,
        )
        if preferred is None:
            return None
        if not _is_priced(preferred):
            raise ModelPricingNotConfiguredError(
                f"Model {model_name} has no price in the catalog, so runs on it could not be billed"
            )
        # Two first adds of the same model race to this insert; the loser's
        # conflict is a no-op and it reads the winner's row.
        await self.session.execute(
            insert(ModelSpec)
            .values(
                workspace_id=self.user_context.workspace_id,
                created_by=self.user_context.user_id,
                provider_spec_id=provider_spec_id,
                model_name=model_name,
                display_name=preferred.display_name,
                description=preferred.description,
                context_window=preferred.context_window,
                max_output_tokens=preferred.max_output_tokens,
                input_cost_per_token=preferred.input_cost_per_token,
                output_cost_per_token=preferred.output_cost_per_token,
                supports_function_calling=preferred.supports_function_calling,
                is_active=preferred.is_active,
            )
            .on_conflict_do_nothing(constraint="uq_model_specs_workspace_provider_model")
        )
        await self.session.commit()
        return await self.find_one_by(provider_spec_id=provider_spec_id, model_name=model_name)

    async def upsert_by_provider_and_model_kwargs(self, **kwargs) -> ModelSpec:
        """Upsert this workspace's spec keyed on ``(provider_spec_id, model_name)``.

        The key is unique per workspace, so another workspace's row for the same
        model is never returned or touched: each workspace prices its own.
        """
        provider_spec_id = kwargs.get("provider_spec_id")
        model_name = kwargs.get("model_name")
        if provider_spec_id is None or model_name is None:
            raise ValueError("provider_spec_id and model_name are required for upsert")
        pid = (
            provider_spec_id if isinstance(provider_spec_id, UUID) else UUID(str(provider_spec_id))
        )
        existing = await self.find_one_by(provider_spec_id=pid, model_name=model_name)
        if existing:
            update_fields = {
                k: v
                for k, v in kwargs.items()
                if k not in ("provider_spec_id", "model_name") and v is not None
            }
            updated = await self.update(existing.id, **update_fields)
            return updated or existing
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
