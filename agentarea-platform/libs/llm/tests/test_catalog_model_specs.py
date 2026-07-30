"""Model spec catalog read-path tests (ADR-003).

Built-in model specs live in the registry catalog (``registry_items`` of
``registry_type='llm_models'``) and are merged into the model-spec list
read-only. Unlike agents/skills there is no copy-on-write fork: built-in specs
are reference specs users instantiate via ``model_instances``. These tests
exercise the repository merge with light fakes, no database.
"""

from datetime import datetime
from uuid import uuid4

import pytest
from agentarea_common.auth.context import UserContext
from agentarea_llm.domain.models import ModelSpec
from agentarea_llm.infrastructure.catalog_model_spec_repository import CatalogModelSpecItem
from agentarea_llm.infrastructure.model_spec_repository import (
    ModelSpecRepository,
    _project_catalog_model_spec,
)

_TS = datetime(2024, 1, 2, 3, 4, 5)


def _item(item_id=None, name="GPT-4", spec=None, provider_spec_id=None, is_active=True, ts=_TS):
    return CatalogModelSpecItem(
        id=item_id or str(uuid4()),
        name=name,
        description="desc",
        version="1",
        spec=spec
        or {
            "model_name": "gpt-4",
            "context_window": 128000,
            "provider_key": "openai",
            "is_active": is_active,
        },
        provider_spec_id=provider_spec_id or str(uuid4()),
        provider_key="openai",
        provider_name="OpenAI",
        created_at=ts,
        updated_at=ts,
    )


class FakeCatalogRepo:
    def __init__(self, items=None):
        self._items = items or []

    async def list_items(self):
        return list(self._items)

    async def get_item(self, item_id):
        return next((i for i in self._items if i.id == item_id), None)


def _repo(catalog):
    uc = UserContext(user_id="u1", workspace_id="w1")
    repo = ModelSpecRepository(session=object(), user_context=uc)
    repo._get_catalog_repository = lambda: catalog
    return repo


def test_project_marks_read_only_with_provider_relation():
    item = _item()
    spec = _project_catalog_model_spec(item)
    assert str(spec.id) == item.id
    assert spec.is_catalog is True
    assert spec.model_name == "gpt-4"
    assert spec.context_window == 128000
    assert str(spec.provider_spec_id) == item.provider_spec_id
    # provider_spec is attached transiently for the API projection.
    assert spec.provider_spec.provider_key == "openai"
    assert spec.provider_spec.name == "OpenAI"


def test_project_carries_registry_item_timestamps():
    """Transient projection never persists, so DB-default timestamps never fire.
    The response schema requires non-null datetimes, so the projection must
    carry the registry item's own timestamps."""
    ts = datetime(2024, 1, 2, 3, 4, 5)
    spec = _project_catalog_model_spec(_item(ts=ts))
    assert spec.created_at == ts
    assert spec.updated_at == ts


def test_catalog_projection_rejects_missing_context_window():
    item = _item(spec={"model_name": "unknown-limit-model"})

    with pytest.raises(KeyError, match="context_window"):
        _project_catalog_model_spec(item)


async def test_catalog_projections_shadows_instantiated_and_projects_rest():
    item_unforked = _item(name="Unforked")
    item_shadowed = _item(name="Shadowed")
    tenant_spec = ModelSpec(
        provider_spec_id=str(uuid4()), model_name="custom", display_name="Custom"
    )
    tenant_spec.registry_item_id = item_shadowed.id  # type: ignore[attr-defined]

    repo = _repo(FakeCatalogRepo([item_unforked, item_shadowed]))
    projections = await repo._catalog_projections(
        [tenant_spec], provider_spec_id=None, is_active=None
    )
    ids = [str(s.id) for s in projections]

    assert item_unforked.id in ids
    assert item_shadowed.id not in ids
    assert all(getattr(s, "is_catalog", False) for s in projections)


async def test_catalog_projections_filter_by_provider_and_active():
    pid = str(uuid4())
    item = _item(name="Active", provider_spec_id=pid, is_active=True)
    inactive = _item(name="Inactive", provider_spec_id=pid, is_active=False)
    repo = _repo(FakeCatalogRepo([item, inactive]))

    from uuid import UUID

    active_only = await repo._catalog_projections([], provider_spec_id=UUID(pid), is_active=True)
    assert {str(s.id) for s in active_only} == {item.id}

    other_provider = await repo._catalog_projections([], provider_spec_id=uuid4(), is_active=None)
    assert other_provider == []


async def test_isolation_builtin_visible_no_foreign_custom_leak():
    """A built-in catalog model spec IS visible to every workspace; another
    workspace's custom spec is NOT (only catalog items are merged in)."""
    item_builtin = _item(name="Shared built-in")
    repo = _repo(FakeCatalogRepo([item_builtin]))
    projections = await repo._catalog_projections([], provider_spec_id=None, is_active=None)
    assert [str(s.id) for s in projections] == [item_builtin.id]
