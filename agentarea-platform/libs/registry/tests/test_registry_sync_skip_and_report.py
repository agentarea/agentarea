"""sync_registry must not let one bad catalog item abort the whole batch.

Reproduces the real llm-models.json incident: a handful of entries (AWS
Bedrock reserved-capacity SKUs) have no per-token price and correctly fail
`_create_llm_model` validation. Before this fix that ValueError propagated out
of `sync_registry` and dropped every other item in the batch, including ones
already persisted earlier in the loop.
"""

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from agentarea_registry.application.service import RegistryService


def _service(registry_type: str = "llm_models"):
    registry_id = uuid4()
    registry = SimpleNamespace(
        id=registry_id,
        registry_type=registry_type,
        source_type="url",
        source_url="https://example.com/catalog.json",
    )
    registry_repo = SimpleNamespace(
        get_by_id=AsyncMock(return_value=registry),
        update=AsyncMock(),
    )

    created: dict[str, SimpleNamespace] = {}

    async def fake_create(**kwargs):
        item = SimpleNamespace(
            id=uuid4(),
            external_id=kwargs["external_id"],
            name=kwargs["name"],
            description=kwargs.get("description"),
            version=kwargs.get("version"),
            spec=kwargs.get("spec") or {},
            tags=kwargs.get("tags") or [],
            installed_entity_id=None,
            installed_version=None,
        )
        created[item.external_id] = item
        return item

    item_repo = SimpleNamespace(
        get_by_external_id=AsyncMock(return_value=None),
        create=AsyncMock(side_effect=fake_create),
        update=AsyncMock(),
        delete=AsyncMock(return_value=True),
        session=SimpleNamespace(commit=AsyncMock(), refresh=AsyncMock()),
    )

    provider = SimpleNamespace(id=uuid4())
    provider_spec_repo = SimpleNamespace(get_by_provider_key=AsyncMock(return_value=provider))

    model = SimpleNamespace(id=uuid4())
    model_spec_repo = SimpleNamespace(
        upsert_by_provider_and_model_kwargs=AsyncMock(return_value=model)
    )

    service = RegistryService(
        registry_repo,
        item_repo,
        server_repo=None,
        provider_spec_repo=provider_spec_repo,
        model_spec_repo=model_spec_repo,
    )
    return service, registry, item_repo, created


def _bedrock_catalog():
    return {
        "models": [
            {
                "provider_key": "aws-bedrock",
                "model_name": "anthropic.claude-3-sonnet",
                "display_name": "Claude 3 Sonnet",
                "context_window": 200_000,
                "input_cost_per_token": 0.000003,
                "output_cost_per_token": 0.000015,
            },
            {
                "provider_key": "aws-bedrock",
                # Reserved-capacity SKU: genuinely has no per-token price.
                "model_name": "1-month-commitment/anthropic.claude-v2:1",
                "display_name": "Claude v2.1 (1-month commitment)",
                "context_window": 100_000,
            },
            {
                "provider_key": "aws-bedrock",
                "model_name": "anthropic.claude-3-haiku",
                "display_name": "Claude 3 Haiku",
                "context_window": 200_000,
                "input_cost_per_token": 0.00000025,
                "output_cost_per_token": 0.00000125,
            },
        ]
    }


async def test_one_priceless_model_is_skipped_and_the_rest_still_sync():
    service, registry, _item_repo, created = _service()

    with patch.object(RegistryService, "_fetch_source", return_value=_bedrock_catalog()):
        stats = await service.sync_registry(registry.id)

    assert stats["new_specs"] == 2
    assert stats["skipped"] == 1
    assert stats["total"] == 3
    assert "aws-bedrock/anthropic.claude-3-sonnet" in created
    assert "aws-bedrock/anthropic.claude-3-haiku" in created


async def test_skip_reason_names_the_rejected_model_and_the_missing_field():
    service, registry, _item_repo, _created = _service()

    with patch.object(RegistryService, "_fetch_source", return_value=_bedrock_catalog()):
        stats = await service.sync_registry(registry.id)

    [detail] = stats["skipped_items"]
    assert detail["external_id"] == "aws-bedrock/1-month-commitment/anthropic.claude-v2:1"
    assert "input_cost_per_token" in detail["reason"]


async def test_rejected_item_does_not_leave_an_orphan_catalog_row():
    service, registry, item_repo, created = _service()

    with patch.object(RegistryService, "_fetch_source", return_value=_bedrock_catalog()):
        await service.sync_registry(registry.id)

    rejected = created["aws-bedrock/1-month-commitment/anthropic.claude-v2:1"]
    item_repo.delete.assert_awaited_once_with(rejected.id)


async def test_skip_is_logged_at_warning_with_exc_info(caplog):
    service, registry, _item_repo, _created = _service()

    with (
        patch.object(RegistryService, "_fetch_source", return_value=_bedrock_catalog()),
        caplog.at_level(logging.WARNING, logger="agentarea_registry.application.service"),
    ):
        await service.sync_registry(registry.id)

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "1-month-commitment/anthropic.claude-v2:1" in warnings[0].getMessage()
    assert warnings[0].exc_info is not None


async def test_all_items_bad_reports_zero_new_specs_without_raising():
    service, registry, _item_repo, _created = _service()
    catalog = {
        "models": [
            {
                "provider_key": "aws-bedrock",
                "model_name": "no-price-a",
                "context_window": 1000,
            },
            {
                "provider_key": "aws-bedrock",
                "model_name": "no-price-b",
                "context_window": 1000,
            },
        ]
    }

    with patch.object(RegistryService, "_fetch_source", return_value=catalog):
        stats = await service.sync_registry(registry.id)

    assert stats["new_specs"] == 0
    assert stats["skipped"] == 2
    assert stats["total"] == 2
    # The registry itself synced successfully; skips are not a sync failure.
    registry_repo_update = service.registry_repo.update
    assert registry_repo_update.await_args.kwargs["last_sync_error"] is None
