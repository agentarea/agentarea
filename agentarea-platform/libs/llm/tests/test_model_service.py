"""ModelService turns a model instance id into a typed client of the kind asked for."""

from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from agentarea_common.constants import MANAGED_BY_PLATFORM
from agentarea_llm.application.model_service import (
    ModelKindMismatchError,
    ModelService,
    ModelUnavailableError,
)
from agentarea_llm.domain.models import ModelKind
from agentarea_llm.infrastructure.model_clients import DecisionModel, ImageModel, VideoModel

WORKSPACE = "ws-1"


def _instance(kind: str, *, managed_by=None, workspace_id=WORKSPACE, spec_workspace=WORKSPACE):
    config = SimpleNamespace(
        api_key="openrouter-key-ref",
        endpoint_url=None,
        managed_by=managed_by,
        workspace_id=workspace_id,
        provider_spec=SimpleNamespace(provider_type="openrouter"),
    )
    spec = SimpleNamespace(
        kind=kind,
        model_name="vendor/model",
        workspace_id=spec_workspace,
        input_cost_per_token=Decimal("0.000001"),
        output_cost_per_token=Decimal("0.000002"),
    )
    instance = SimpleNamespace(
        id=uuid4(),
        is_active=True,
        workspace_id=workspace_id,
        provider_config=config,
        model_spec=spec,
    )
    from agentarea_llm.domain.models import ModelInstance

    instance.foreign_part = lambda: ModelInstance.foreign_part(instance)  # type: ignore[arg-type]
    return instance


class _Instances:
    def __init__(self, *instances):
        self._by_id = {i.id: i for i in instances}

    async def get_with_relations(self, instance_id):
        return self._by_id.get(instance_id)


def _service(*instances, resolved: list | None = None) -> ModelService:
    async def resolve(reference, managed_by):
        if resolved is not None:
            resolved.append((reference, managed_by))
        return "sk-resolved"

    return ModelService(
        instances=_Instances(*instances),
        api_key_resolver=resolve,
        http_client_factory=lambda endpoint: httpx.AsyncClient(),
    )


@pytest.mark.parametrize(
    "kind, method, client_type",
    [
        (ModelKind.IMAGE, "image_model", ImageModel),
        (ModelKind.VIDEO, "video_model", VideoModel),
        (ModelKind.DECISION, "decision_model", DecisionModel),
    ],
)
async def test_each_kind_gets_its_client(kind, method, client_type):
    instance = _instance(kind.value)

    client = await getattr(_service(instance), method)(instance.id)

    assert isinstance(client, client_type)


async def test_the_endpoint_carries_the_resolved_credential_not_the_reference():
    resolved: list = []
    instance = _instance("image", managed_by=MANAGED_BY_PLATFORM)

    endpoint = await _service(instance, resolved=resolved).resolve(instance.id, ModelKind.IMAGE)

    assert resolved == [("openrouter-key-ref", MANAGED_BY_PLATFORM)]
    assert endpoint.api_key == "sk-resolved"
    assert endpoint.managed_by == MANAGED_BY_PLATFORM
    assert endpoint.model_name == "vendor/model"
    assert endpoint.provider_type == "openrouter"
    assert endpoint.instance_id == str(instance.id)


async def test_a_model_of_another_kind_is_refused():
    instance = _instance("chat")

    with pytest.raises(ModelKindMismatchError, match="chat"):
        await _service(instance).image_model(instance.id)


async def test_an_unknown_instance_is_refused():
    with pytest.raises(ModelUnavailableError, match="not found"):
        await _service().video_model(uuid4())


async def test_an_inactive_instance_is_refused():
    instance = _instance("video")
    instance.is_active = False

    with pytest.raises(ModelUnavailableError, match="inactive"):
        await _service(instance).video_model(instance.id)


async def test_an_instance_on_a_foreign_config_is_refused():
    instance = _instance("decision")
    instance.provider_config.workspace_id = "someone-else"

    with pytest.raises(ModelUnavailableError, match="provider_config"):
        await _service(instance).decision_model(instance.id)
