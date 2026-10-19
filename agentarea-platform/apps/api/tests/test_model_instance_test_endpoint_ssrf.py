"""The model test refuses a private member endpoint and never echoes the provider.

GHSA-pprc-x767-m6jg: ``/model-instances/test`` called a member-set endpoint_url
on any address and returned the upstream body in ``message``, which made every
host the API pod could reach readable.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from agentarea_agents_sdk.models import LLMModel
from agentarea_api.api.v1 import model_instances
from agentarea_api.api.v1.model_instances import ModelInstanceTestRequest
from agentarea_common.auth.context import UserContext
from agentarea_common.constants import MANAGED_BY_PLATFORM
from agentarea_llm.domain.models import ModelKind
from fastapi import HTTPException

MEMBER = UserContext(user_id="user-member", workspace_id="ws-acme", admin_workspaces=[])


def _service(endpoint_url: str, managed_by: str | None = None) -> SimpleNamespace:
    config = SimpleNamespace(
        provider_spec=SimpleNamespace(provider_type="openai"),
        endpoint_url=endpoint_url,
        api_key="provider_config_key",  # pragma: allowlist secret
        managed_by=managed_by,
    )
    spec = SimpleNamespace(kind=ModelKind.CHAT, model_name="gpt-4o-mini")
    return SimpleNamespace(
        get_provider_config=AsyncMock(return_value=config),
        get_model_spec=AsyncMock(return_value=spec),
        secret_manager=SimpleNamespace(get_secret=AsyncMock(return_value="attacker-chosen")),
    )


def _request() -> ModelInstanceTestRequest:
    return ModelInstanceTestRequest(
        provider_config_id=uuid4(), model_spec_id=uuid4(), test_message="p"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "endpoint_url",
    [
        "http://localhost:8000",
        "http://127.0.0.1:4434",
        "http://10.110.1.40:8080/v1",
        "http://169.254.169.254",
    ],
)
async def test_a_member_endpoint_on_a_private_address_is_refused(endpoint_url):
    result = await model_instances.validate_model_instance(
        _request(), MEMBER, _service(endpoint_url)
    )

    assert result.success is False
    assert result.error_type == "EndpointRefused"


@pytest.mark.asyncio
async def test_the_provider_answer_is_never_echoed(monkeypatch):
    class _UpstreamError(Exception):
        status_code = 404

    async def fail(_self, _request):
        raise _UpstreamError("404 page not found: INTERNAL-BODY")

    monkeypatch.setattr(LLMModel, "complete", fail)

    result = await model_instances.validate_model_instance(
        _request(), MEMBER, _service("https://93.184.216.34/v1")
    )

    assert result.success is False
    assert "INTERNAL-BODY" not in result.message
    assert "404" in result.message


@pytest.mark.asyncio
async def test_a_platform_model_is_never_called_by_a_test(monkeypatch):
    called = AsyncMock()
    monkeypatch.setattr(LLMModel, "complete", called)
    service = _service("https://llm-gateway.internal/v1", managed_by=MANAGED_BY_PLATFORM)

    with pytest.raises(HTTPException) as refused:
        await model_instances.validate_model_instance(_request(), MEMBER, service)

    assert refused.value.status_code == 403
    called.assert_not_called()
    service.secret_manager.get_secret.assert_not_called()
