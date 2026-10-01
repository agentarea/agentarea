"""Model spec catalog read-path tests (ADR-003).

Built-in model specs live in the registry catalog (``registry_items`` of
``registry_type='llm_models'``) and are merged into the model-spec list
read-only, one entry per model, hidden once the workspace has its own row for
it. These tests exercise the repository merge with light fakes, no database;
``test_catalog_model_instance_db.py`` covers adding one to a workspace.
"""

from datetime import datetime
from uuid import uuid4

import pytest
from agentarea_common.auth.context import UserContext
from agentarea_llm.infrastructure.catalog_model_spec_repository import CatalogModelSpecItem
from agentarea_llm.infrastructure.model_spec_repository import (
    ModelSpecRepository,
    _project_catalog_model_spec,
)

_TS = datetime(2024, 1, 2, 3, 4, 5)
_PRICES = {"input_cost_per_token": "0.000001", "output_cost_per_token": "0.000002"}


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
            **_PRICES,
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


def _spec(model_name):
    return {
        "model_name": model_name,
        "context_window": 128000,
        "provider_key": "openai",
        **_PRICES,
    }


async def test_catalog_projections_shadows_the_workspaces_own_models_and_projects_rest():
    item_unforked = _item(name="Unforked", spec=_spec("gpt-4"))
    item_shadowed = _item(name="Shadowed", spec=_spec("gpt-5"))

    repo = _repo(FakeCatalogRepo([item_unforked, item_shadowed]))
    projections = await repo._catalog_projections(
        {(item_shadowed.provider_spec_id, "gpt-5")}, provider_spec_id=None, is_active=None
    )
    ids = [str(s.id) for s in projections]

    assert item_unforked.id in ids
    assert item_shadowed.id not in ids
    assert all(getattr(s, "is_catalog", False) for s in projections)


async def test_catalog_projections_project_a_model_in_several_registries_once():
    pid = str(uuid4())
    first = _item(name="GPT-4", provider_spec_id=pid)
    second = _item(name="GPT-4", provider_spec_id=pid)

    repo = _repo(FakeCatalogRepo([first, second]))
    projections = await repo._catalog_projections(set(), provider_spec_id=None, is_active=None)

    assert [str(s.id) for s in projections] == [first.id]


async def test_catalog_projections_leave_out_a_model_without_a_price():
    pid = str(uuid4())
    priced = _item(name="Priced", provider_spec_id=pid, spec=_spec("gpt-4"))
    unpriced = _item(
        name="Unpriced",
        provider_spec_id=pid,
        spec={**_spec("router"), "output_cost_per_token": None},
    )

    repo = _repo(FakeCatalogRepo([priced, unpriced]))
    projections = await repo._catalog_projections(set(), provider_spec_id=None, is_active=None)

    assert [str(s.id) for s in projections] == [priced.id]


async def test_an_unpriced_preferred_copy_is_not_replaced_by_a_lesser_registrys():
    pid = str(uuid4())
    preferred = _item(provider_spec_id=pid, spec={**_spec("gpt-4"), "input_cost_per_token": None})
    lesser = _item(provider_spec_id=pid, spec=_spec("gpt-4"))

    repo = _repo(FakeCatalogRepo([preferred, lesser]))
    projections = await repo._catalog_projections(set(), provider_spec_id=None, is_active=None)

    assert projections == []


async def test_catalog_projections_filter_by_provider_and_active():
    pid = str(uuid4())
    item = _item(name="Active", provider_spec_id=pid, is_active=True)
    inactive = _item(
        name="Inactive",
        provider_spec_id=pid,
        spec={**_spec("gpt-3"), "is_active": False},
    )
    repo = _repo(FakeCatalogRepo([item, inactive]))

    from uuid import UUID

    active_only = await repo._catalog_projections(set(), provider_spec_id=UUID(pid), is_active=True)
    assert {str(s.id) for s in active_only} == {item.id}

    other_provider = await repo._catalog_projections(set(), provider_spec_id=uuid4(), is_active=None)
    assert other_provider == []


async def test_isolation_builtin_visible_no_foreign_custom_leak():
    """A built-in catalog model spec IS visible to every workspace; another
    workspace's custom spec is NOT (only catalog items are merged in)."""
    item_builtin = _item(name="Shared built-in")
    repo = _repo(FakeCatalogRepo([item_builtin]))
    projections = await repo._catalog_projections(set(), provider_spec_id=None, is_active=None)
    assert [str(s.id) for s in projections] == [item_builtin.id]


def test_projection_carries_the_catalog_kind():
    spec = _project_catalog_model_spec(
        _item(spec={"model_name": "veo", "provider_key": "openrouter", "kind": "video"})
    )

    assert spec.kind == "video"
    assert spec.context_window is None


def test_projection_of_an_item_without_kind_is_chat():
    assert _project_catalog_model_spec(_item()).kind == "chat"


async def test_a_media_model_is_projected_without_token_prices():
    pid = str(uuid4())
    video = _item(
        name="Veo",
        provider_spec_id=pid,
        spec={"model_name": "veo", "provider_key": "openrouter", "kind": "video"},
    )

    repo = _repo(FakeCatalogRepo([video]))
    projections = await repo._catalog_projections(set(), provider_spec_id=None, is_active=None)

    assert [str(s.id) for s in projections] == [video.id]


async def test_catalog_projections_filter_by_kind():
    pid = str(uuid4())
    chat = _item(name="Chat", provider_spec_id=pid, spec=_spec("gpt-4"))
    image = _item(
        name="Image",
        provider_spec_id=pid,
        spec={"model_name": "flux", "provider_key": "openai", "kind": "image"},
    )

    repo = _repo(FakeCatalogRepo([chat, image]))
    projections = await repo._catalog_projections(
        set(), provider_spec_id=None, is_active=None, kind="image"
    )

    assert [str(s.id) for s in projections] == [image.id]
