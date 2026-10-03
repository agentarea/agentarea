"""The address an LLM call is sent to, vetted at the moment of use.

A member sets ``endpoint_url`` on their own provider config; every run, model
test and compaction then POSTs to it from inside the deployment. The write path
refuses non-public addresses (``ProviderService``); this re-checks at use, so a
row stored before that check, or under a policy that has since tightened, is
refused before any request is made. Platform-managed configs carry the
operator's own endpoint and are trusted.

What it does not cover: the check resolves the name and returns a string; the
LLM client (LiteLLM, the OpenAI SDK, the direct streaming path) resolves it
again when it connects, and LiteLLM and the OpenAI SDK follow redirects. A
public endpoint that answers with a redirect to an internal address, or a name
that resolves to a public address for the check and a private one for the
connection (DNS rebinding), still reaches that address. Those requests do not
go through the pinned ``safe_async_client``, because LiteLLM builds a
different HTTP client per provider. Containing them is the job of the egress
network policy described in :mod:`agentarea_common.utils.url_safety`.
"""

from __future__ import annotations

import asyncio

from agentarea_common.constants import MANAGED_BY_PLATFORM
from agentarea_common.utils.url_safety import (
    OutboundPolicy,
    UnsafeUrlError,
    validate_outbound_url,
)


class UnsafeLLMEndpointError(ValueError):
    """The provider endpoint is not an address this deployment may call."""


async def guarded_llm_endpoint(
    endpoint_url: str | None,
    *,
    managed_by: str | None,
    local_host: str | None = None,
) -> str | None:
    """Return the endpoint to call, refusing a member-set non-public address.

    ``local_host`` maps ``localhost``/``127.0.0.1`` to the host a containerised
    runtime reaches the machine's own services on; it applies only after the
    address the member stored has been admitted.
    """
    if not endpoint_url:
        return None
    if managed_by != MANAGED_BY_PLATFORM:
        try:
            await asyncio.to_thread(
                validate_outbound_url, endpoint_url, policy=OutboundPolicy.from_env()
            )
        except UnsafeUrlError as exc:
            raise UnsafeLLMEndpointError(f"LLM endpoint is not an allowed address: {exc}") from exc
    if local_host:
        endpoint_url = endpoint_url.replace("localhost", local_host).replace(
            "127.0.0.1", local_host
        )
    return endpoint_url
