"""ModelService turns a model instance id into a typed client of the kind asked for.

A call is described, funded, and only then connected: the platform's credential is
read for a call billing funded, never for one it did not.
"""

from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from agentarea_common.constants import MANAGED_BY_PLATFORM
from agentarea_common.model_charges import ModelFunding, UnfundedPlatformCallError, require_funding
from agentarea_llm.application.model_service import (
    ModelKindMismatchError,
    ModelService,
    ModelUnavailableError,
)
from agentarea_llm.application.provider_credentials import resolve_provider_api_key
from agentarea_llm.domain.models import ModelKind
from agentarea_llm.infrastructure.model_clients import DecisionModel, ImageModel, VideoModel

WORKSPACE = "ws-1"


def _instance(kind: str, *, managed_by=None, workspace_id=WORKSPACE, spec_workspace=WORKSPACE):
    config = SimpleNamespace(
        api_key="openrouter-key-ref",  # pragma: allowlist secret
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
    async def resolve(reference, managed_by, funding):
        require_funding(funding, managed_by)
        if resolved is not None:
            resolved.append((reference, managed_by, funding))
        return "sk-resolved"

    return ModelService(
        instances=_Instances(*instances),
        api_key_resolver=resolve,
        http_client_factory=lambda endpoint: httpx.AsyncClient(),
    )


def _funding(instance, *, platform_funded=False, hold_id=None) -> ModelFunding:
    return ModelFunding(
        model_instance_id=str(instance.id), platform_funded=platform_funded, hold_id=hold_id
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
    service = _service(instance)

    target = await service.describe(instance.id, kind)
    client = await getattr(service, method)(target, _funding(instance))

    assert isinstance(client, client_type)


async def test_a_target_names_the_credential_without_reading_it():
    resolved: list = []
    instance = _instance("image", managed_by=MANAGED_BY_PLATFORM)

    target = await _service(instance, resolved=resolved).describe(instance.id, ModelKind.IMAGE)

    assert resolved == []
    assert target.api_key_reference == "openrouter-key-ref"  # pragma: allowlist secret
    assert not hasattr(target, "api_key")


async def test_the_endpoint_carries_the_resolved_credential_not_the_reference():
    resolved: list = []
    instance = _instance("image", managed_by=MANAGED_BY_PLATFORM)
    service = _service(instance, resolved=resolved)
    funding = _funding(instance, platform_funded=True, hold_id="hold-1")

    endpoint = await service.connect(await service.describe(instance.id, ModelKind.IMAGE), funding)

    assert resolved == [("openrouter-key-ref", MANAGED_BY_PLATFORM, funding)]
    assert endpoint.api_key == "sk-resolved"  # pragma: allowlist secret
    assert endpoint.managed_by == MANAGED_BY_PLATFORM
    assert endpoint.model_name == "vendor/model"
    assert endpoint.provider_type == "openrouter"
    assert endpoint.instance_id == str(instance.id)


async def test_the_platforms_credential_is_refused_to_a_call_billing_did_not_fund():
    resolved: list = []
    instance = _instance("image", managed_by=MANAGED_BY_PLATFORM)
    service = _service(instance, resolved=resolved)
    target = await service.describe(instance.id, ModelKind.IMAGE)

    with pytest.raises(UnfundedPlatformCallError):
        await service.connect(target, _funding(instance, platform_funded=False))
    with pytest.raises(UnfundedPlatformCallError):
        await service.image_model(target, _funding(instance, platform_funded=False))
    assert resolved == []


async def test_the_customers_own_credential_needs_no_hold():
    instance = _instance("image")
    service = _service(instance)

    endpoint = await service.connect(
        await service.describe(instance.id, ModelKind.IMAGE), _funding(instance)
    )

    assert endpoint.api_key == "sk-resolved"  # pragma: allowlist secret


async def test_a_funding_pays_only_for_the_model_it_was_made_for():
    instance, other = _instance("image"), _instance("image")
    service = _service(instance, other)
    target = await service.describe(instance.id, ModelKind.IMAGE)

    with pytest.raises(ValueError, match="cannot pay"):
        await service.connect(target, _funding(other))


@pytest.mark.parametrize("funding", [None, ModelFunding(model_instance_id="m", platform_funded=False)])
async def test_the_platforms_secret_is_not_read_without_a_funded_call(funding):
    def no_secrets(**_):
        raise AssertionError("no secret is read for an unfunded call")

    with pytest.raises(UnfundedPlatformCallError):
        await resolve_provider_api_key(
            reference="openrouter-key-ref",  # pragma: allowlist secret
            managed_by=MANAGED_BY_PLATFORM,
            funding=funding,
            user_context=SimpleNamespace(user_id="u", workspace_id=WORKSPACE),  # type: ignore[arg-type]
            secret_manager_factory=SimpleNamespace(create=no_secrets),  # type: ignore[arg-type]
        )


async def test_a_model_of_another_kind_is_refused():
    instance = _instance("chat")

    with pytest.raises(ModelKindMismatchError, match="chat"):
        await _service(instance).describe(instance.id, ModelKind.IMAGE)


async def test_an_unknown_instance_is_refused():
    with pytest.raises(ModelUnavailableError, match="not found"):
        await _service().describe(uuid4(), ModelKind.VIDEO)


async def test_an_inactive_instance_is_refused():
    instance = _instance("video")
    instance.is_active = False

    with pytest.raises(ModelUnavailableError, match="inactive"):
        await _service(instance).describe(instance.id, ModelKind.VIDEO)


async def test_an_instance_on_a_foreign_config_is_refused():
    instance = _instance("decision")
    instance.provider_config.workspace_id = "someone-else"

    with pytest.raises(ModelUnavailableError, match="provider_config"):
        await _service(instance).describe(instance.id, ModelKind.DECISION)
