"""Every HTTP request the platform sends leaves through here, by where it goes.

A caller names its destination, never a client type:

- ``MEMBER``: an address a workspace member set, directly or through a document
  (an MCP URL, an OpenAPI base URL, a provider endpoint). Every hop is resolved,
  vetted against the outbound policy and pinned (``safe_async_client``).
- ``VENDOR``: a fixed third-party service the platform integrates with (Telegram,
  GitHub, an LLM vendor's public API). It goes through the deployment's egress
  proxy when one is configured and trusts the deployment's extra CAs.
- ``INTERNAL``: a service of the deployment itself (the MCP manager, Hydra,
  Kratos, OpenFGA). It is called directly, never through the egress proxy.

A member's host for a protocol other than HTTP (SMTP, IMAP) is vetted the same
way: ``member_address`` resolves it and refuses it unless every address passes the
policy, and ``member_connection`` opens a TCP connection to the vetted address,
so the name cannot resolve elsewhere between the check and the connect.

Routing every request through one place is what lets a deployment move its
egress behind a proxy, or tighten it, without touching each module.
``tests/unit/test_outbound_ratchet.py`` counts the clients still built elsewhere.
"""

import asyncio
import ipaddress
import socket
from collections.abc import Callable
from enum import StrEnum
from typing import Any

import httpx

from agentarea_common.utils.outbound_tls import outbound_ssl_context
from agentarea_common.utils.url_safety import (
    OutboundPolicy,
    Resolver,
    SafeOutboundTransport,
    UnsafeUrlError,
    resolve_host,
    safe_async_client,
)

__all__ = ["Destination", "member_address", "member_connection", "outbound_client"]


class Destination(StrEnum):
    MEMBER = "member"
    VENDOR = "vendor"
    INTERNAL = "internal"


def outbound_client(
    destination: Destination,
    *,
    policy: OutboundPolicy | None = None,
    wrap: Callable[[httpx.AsyncBaseTransport], httpx.AsyncBaseTransport] | None = None,
    **kwargs: Any,
) -> httpx.AsyncClient:
    """The client for requests to ``destination``.

    Takes the ``httpx.AsyncClient`` keyword arguments except ``transport``,
    ``verify`` and ``trust_env``, which the destination decides. ``policy`` applies
    to a member's address only; it defaults to the deployment's. ``wrap`` puts a
    transport of a member's address behind another, such as a payment SDK's that
    retries a request with a payment: every request it sends still goes through
    the vetted, pinned transport.
    """
    if destination is Destination.MEMBER:
        if wrap is None:
            return safe_async_client(policy=policy, **kwargs)
        inner = SafeOutboundTransport(policy or OutboundPolicy.from_env())
        return httpx.AsyncClient(transport=wrap(inner), **kwargs)
    if policy is not None or wrap is not None:
        raise ValueError(
            f"an outbound policy or wrapped transport applies to member addresses, not {destination}"
        )
    if destination is Destination.VENDOR:
        return httpx.AsyncClient(verify=outbound_ssl_context(), trust_env=True, **kwargs)
    return httpx.AsyncClient(verify=outbound_ssl_context(), trust_env=False, **kwargs)


async def member_address(
    host: str,
    port: int,
    *,
    policy: OutboundPolicy | None = None,
    resolve: Resolver = resolve_host,
) -> str:
    """The address to connect to for a host a member set, every address of it vetted.

    Connect to the returned address and keep ``host`` as the TLS server name.
    Raises ``UnsafeUrlError`` when the host does not resolve or any of its
    addresses is one the policy refuses.
    """
    policy = policy or OutboundPolicy.from_env()
    try:
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            addresses = [ipaddress.ip_address(address) for address in await resolve(host, port)]
        except OSError as error:
            raise UnsafeUrlError(f"Could not resolve host {host!r}") from error
    if not addresses:
        raise UnsafeUrlError(f"Host {host!r} has no address")
    for address in addresses:
        if not policy.permits(host, address):
            raise UnsafeUrlError(
                f"Host {host!r} resolves to non-public address {address}; refusing to connect"
            )
    return str(addresses[0])


async def member_connection(
    host: str,
    port: int,
    *,
    policy: OutboundPolicy | None = None,
    resolve: Resolver = resolve_host,
    timeout: float = 30.0,
) -> socket.socket:
    """A TCP connection to a host a member set, made to the address it was vetted at."""
    address = await member_address(host, port, policy=policy, resolve=resolve)
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    sock.setblocking(False)
    try:
        await asyncio.wait_for(
            asyncio.get_running_loop().sock_connect(sock, (address, port)), timeout
        )
    except BaseException:
        sock.close()
        raise
    return sock
