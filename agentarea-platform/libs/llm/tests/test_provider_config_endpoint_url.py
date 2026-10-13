"""A provider config refuses, when saved, an endpoint every call would refuse."""

import pytest
from agentarea_common.exceptions.errors import BadRequestError
from agentarea_llm.application.provider_service import (
    ENDPOINT_NOT_ALLOWED,
    assert_endpoint_allowed,
)
from agentarea_llm.schemas.dto import ProviderConfigCreate, ProviderConfigUpdate
from pydantic import ValidationError


def _create(endpoint_url: str | None) -> ProviderConfigCreate:
    return ProviderConfigCreate(
        provider_spec_id="00000000-0000-0000-0000-000000000001",
        name="byok",
        endpoint_url=endpoint_url,
    )


@pytest.mark.parametrize(
    "endpoint_url",
    [
        "file:///etc/passwd",
        "gopher://93.184.216.34/",
        "http:///v1",
        "https://93.184.216.34/health?",
        "https://93.184.216.34/v1?x=1",
        "https://93.184.216.34/v1#a",
    ],
)
def test_a_malformed_endpoint_is_refused(endpoint_url):
    # "?" would turn the appended provider path into a query string and give the
    # member the full path on the host.
    with pytest.raises(ValidationError):
        _create(endpoint_url)
    with pytest.raises(ValidationError):
        ProviderConfigUpdate(endpoint_url=endpoint_url)


def test_unset_and_cleared_endpoints_are_accepted():
    assert _create(None).endpoint_url is None
    assert ProviderConfigUpdate(endpoint_url="").endpoint_url == ""


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "endpoint_url",
    [
        "http://127.0.0.1:8000/v1",
        "http://localhost:4434",
        "http://10.110.1.40:8080/v1",
        "http://169.254.169.254",
        "http://this-host-does-not-exist-aa123.invalid/v1",
    ],
)
async def test_a_private_or_unresolvable_endpoint_is_refused_with_one_message(endpoint_url):
    with pytest.raises(BadRequestError) as refused:
        await assert_endpoint_allowed(endpoint_url)
    assert refused.value.detail == ENDPOINT_NOT_ALLOWED


@pytest.mark.asyncio
async def test_a_public_endpoint_is_accepted():
    await assert_endpoint_allowed("https://93.184.216.34/v1")
