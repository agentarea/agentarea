"""A member-set LLM endpoint is POSTed to from inside the deployment on every
run; a non-public address there reaches cloud metadata or internal services."""

import pytest
from agentarea_common.constants import MANAGED_BY_PLATFORM
from agentarea_common.utils.llm_endpoint import UnsafeLLMEndpointError, guarded_llm_endpoint


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    ["http://169.254.169.254/latest/meta-data/?", "http://127.0.0.1:8000/v1", "http://10.0.0.5/v1"],
)
async def test_member_endpoint_on_a_private_address_is_refused(url: str) -> None:
    with pytest.raises(UnsafeLLMEndpointError):
        await guarded_llm_endpoint(url, managed_by=None)


@pytest.mark.asyncio
async def test_platform_managed_endpoint_is_trusted() -> None:
    url = "http://litellm.agentarea.svc.cluster.local:4000/v1"
    assert await guarded_llm_endpoint(url, managed_by=MANAGED_BY_PLATFORM) == url


@pytest.mark.asyncio
async def test_allowlisted_localhost_is_admitted_then_mapped(monkeypatch) -> None:
    from agentarea_common.config import get_settings

    monkeypatch.setattr(get_settings().app, "OUTBOUND_PRIVATE_ALLOWLIST", "localhost")
    mapped = await guarded_llm_endpoint(
        "http://localhost:11434/v1", managed_by=None, local_host="host.docker.internal"
    )
    assert mapped == "http://host.docker.internal:11434/v1"
