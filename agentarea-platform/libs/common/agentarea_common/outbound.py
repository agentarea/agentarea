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

Routing every request through one place is what lets a deployment move its
egress behind a proxy, or tighten it, without touching each module.
``tests/unit/test_outbound_ratchet.py`` counts the clients still built elsewhere.
"""

from enum import StrEnum
from typing import Any

import httpx

from agentarea_common.utils.outbound_tls import outbound_ssl_context
from agentarea_common.utils.url_safety import OutboundPolicy, safe_async_client

__all__ = ["Destination", "outbound_client"]


class Destination(StrEnum):
    MEMBER = "member"
    VENDOR = "vendor"
    INTERNAL = "internal"


def outbound_client(
    destination: Destination, *, policy: OutboundPolicy | None = None, **kwargs: Any
) -> httpx.AsyncClient:
    """The client for requests to ``destination``.

    Takes the ``httpx.AsyncClient`` keyword arguments except ``transport``,
    ``verify`` and ``trust_env``, which the destination decides. ``policy`` applies
    to a member's address only; it defaults to the deployment's.
    """
    if destination is Destination.MEMBER:
        return safe_async_client(policy=policy, **kwargs)
    if policy is not None:
        raise ValueError(f"an outbound policy applies to member addresses, not {destination}")
    if destination is Destination.VENDOR:
        return httpx.AsyncClient(verify=outbound_ssl_context(), trust_env=True, **kwargs)
    return httpx.AsyncClient(verify=outbound_ssl_context(), trust_env=False, **kwargs)
