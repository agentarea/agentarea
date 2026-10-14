"""Each destination gets the client its trust calls for."""

import asyncio

import httpx
import pytest
from agentarea_common.outbound import (
    Destination,
    member_address,
    member_connection,
    outbound_client,
)
from agentarea_common.utils.url_safety import (
    OutboundPolicy,
    SafeOutboundTransport,
    UnsafeDestinationError,
    UnsafeUrlError,
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
def test_a_policy_or_a_wrap_is_refused_for_anything_but_a_member_address(destination):
    with pytest.raises(ValueError, match="member addresses"):
        outbound_client(destination, policy=OutboundPolicy())
    with pytest.raises(ValueError, match="member addresses"):
        outbound_client(destination, wrap=lambda inner: inner)


class _Retrying(httpx.AsyncBaseTransport):
    """A payment SDK's transport: it sends, and may send again, through ``inner``."""

    def __init__(self, inner):
        self.inner = inner

    async def handle_async_request(self, request):
        return await self.inner.handle_async_request(request)


async def test_a_wrapping_transport_still_sends_through_the_pinned_one():
    async with outbound_client(
        Destination.MEMBER, policy=OutboundPolicy(), wrap=_Retrying
    ) as client:
        assert isinstance(client._transport, _Retrying)
        assert isinstance(client._transport.inner, SafeOutboundTransport)
        with pytest.raises(UnsafeDestinationError):
            await client.get("http://10.0.0.5/")


def _resolving_to(*addresses):
    async def resolve(host, port):
        return list(addresses)

    return resolve


async def test_a_member_host_is_refused_when_any_of_its_addresses_is_private():
    with pytest.raises(UnsafeUrlError, match="non-public address 10.0.0.5"):
        await member_address(
            "mail.example.test",
            25,
            policy=OutboundPolicy(),
            resolve=_resolving_to("8.8.8.8", "10.0.0.5"),
        )


async def test_a_member_host_resolves_to_the_address_it_was_vetted_at():
    address = await member_address(
        "mail.example.test", 25, policy=OutboundPolicy(), resolve=_resolving_to("8.8.8.8")
    )
    assert address == "8.8.8.8"


async def test_a_literal_private_address_is_refused_without_resolving():
    with pytest.raises(UnsafeUrlError, match="169.254.169.254"):
        await member_address("169.254.169.254", 993, policy=OutboundPolicy())


async def test_the_connection_is_made_to_the_vetted_address():
    server = await asyncio.start_server(lambda reader, writer: writer.close(), "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        sock = await member_connection(
            "mail.example.test",
            port,
            policy=OutboundPolicy(private_allowlist=("127.0.0.1/32",)),
            resolve=_resolving_to("127.0.0.1"),
        )
        assert sock.getpeername() == ("127.0.0.1", port)
        sock.close()
    finally:
        server.close()
        await server.wait_closed()
