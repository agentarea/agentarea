"""Each destination gets the client its trust calls for."""

import httpx
import pytest
from agentarea_common.outbound import Destination, outbound_client
from agentarea_common.utils.url_safety import (
    OutboundPolicy,
    SafeOutboundTransport,
    UnsafeDestinationError,
)


async def test_a_member_address_goes_through_the_pinned_transport():
    async with outbound_client(Destination.MEMBER, policy=OutboundPolicy()) as client:
        assert isinstance(client._transport, SafeOutboundTransport)
        with pytest.raises(UnsafeDestinationError):
            await client.get("http://127.0.0.1:9/")


async def test_a_vendor_honours_the_egress_proxy_and_an_internal_service_never_does(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://egress.example:3128")

    async with outbound_client(Destination.VENDOR) as vendor:
        assert vendor.trust_env is True
        assert any(
            isinstance(mount, httpx.AsyncHTTPTransport) and pattern.scheme == "https"
            for pattern, mount in vendor._mounts.items()
        )
    async with outbound_client(Destination.INTERNAL) as internal:
        assert internal.trust_env is False
        assert not internal._mounts


@pytest.mark.parametrize("destination", [Destination.VENDOR, Destination.INTERNAL])
def test_a_policy_is_refused_for_anything_but_a_member_address(destination):
    with pytest.raises(ValueError, match="member addresses"):
        outbound_client(destination, policy=OutboundPolicy())
