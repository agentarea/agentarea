"""A subscriber's callback endpoint: checked, challenged, and posted to (SEP-3415 webhook delivery).

Every request goes through the member-address client (``Destination.MEMBER``):
each hop resolved, vetted against the outbound policy and pinned, no redirects.
A callback must be ``https``. The one exception is a development receiver: a
host that resolves only to private addresses the deployment's outbound policy
admits (``AGENTAREA_HTTP_PRIVATE_ALLOWLIST`` / ``AGENTAREA_HTTP_ALLOW_PRIVATE``)
may be ``http``.

What a failure reports is one of the SEP's categories, never the endpoint's
response, so the platform is no oracle for what sits at an address.
"""

import hmac
import ipaddress
import json
import logging
import ssl
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx
from agentarea_common.outbound import Destination, outbound_client
from agentarea_common.utils.url_safety import (
    OutboundPolicy,
    Resolver,
    UnsafeDestinationError,
    resolve_host,
)

from ..domain.mcp_events import (
    ErrorCode,
    EventsError,
    control_message_id,
    delivery_headers,
    encode_body,
)

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 10.0
MAX_URL_LENGTH = 2048
#: Answers that a retry would not change: the receiver refused the event for good.
FINAL_STATUSES = frozenset({410, 413})


@dataclass(frozen=True)
class PostOutcome:
    """``error`` is None on a 2xx; otherwise a SEP ``lastError`` category."""

    error: str | None
    final: bool = False
    body: bytes = b""


def _category(error: Exception) -> str:
    if isinstance(error, httpx.TimeoutException):
        return "timeout"
    cause: BaseException | None = error
    while cause is not None:
        if isinstance(cause, ssl.SSLError):
            return "tls_error"
        cause = cause.__cause__ or cause.__context__
    return "connection_refused"


class WebhookEndpoint:
    def __init__(
        self,
        *,
        policy: OutboundPolicy | None = None,
        resolve: Resolver = resolve_host,
        client_factory: Callable[[], httpx.AsyncClient] | None = None,
        clock: Callable[[], float] = time.time,
    ):
        self._policy = policy
        self._resolve = resolve
        self._client_factory = client_factory or (
            lambda: outbound_client(
                Destination.MEMBER,
                policy=self._policy,
                timeout=TIMEOUT_SECONDS,
                follow_redirects=False,
            )
        )
        self._clock = clock

    def _current_policy(self) -> OutboundPolicy:
        return self._policy or OutboundPolicy.from_env()

    async def check(self, url: str) -> None:
        """Refuse a callback URL that is not ``https`` (or a development receiver's ``http``)."""
        if len(url) > MAX_URL_LENGTH:
            raise EventsError(ErrorCode.INVALID_PARAMS, "delivery.url is too long")
        parts = urlsplit(url)
        if not parts.hostname:
            raise EventsError(ErrorCode.INVALID_PARAMS, "delivery.url has no host")
        if parts.scheme == "https":
            return
        if parts.scheme == "http" and await self._development_receiver(parts.hostname, parts.port):
            return
        raise EventsError(ErrorCode.INVALID_PARAMS, "delivery.url must be https")

    async def _development_receiver(self, host: str, port: int | None) -> bool:
        policy = self._current_policy()
        try:
            addresses = [ipaddress.ip_address(host)]
        except ValueError:
            try:
                addresses = [ipaddress.ip_address(a) for a in await self._resolve(host, port or 80)]
            except OSError:
                return False
        return bool(addresses) and all(
            not address.is_global and policy.permits(host, address) for address in addresses
        )

    async def post(
        self, *, url: str, secret: str, subscription: str, message_id: str, body: dict[str, Any]
    ) -> PostOutcome:
        """One signed POST; a fresh timestamp and signature each time."""
        raw = encode_body(body)
        headers = delivery_headers(
            secret=secret,
            message_id=message_id,
            timestamp=int(self._clock()),
            body=raw,
            subscription=subscription,
        )
        try:
            async with self._client_factory() as client:
                response = await client.post(url, content=raw, headers=headers)
        except UnsafeDestinationError:
            logger.warning(
                "Callback of subscription %s points where the policy refuses", subscription
            )
            return PostOutcome(error="connection_refused")
        except httpx.HTTPError as error:
            logger.warning(
                "POST to the callback of subscription %s failed", subscription, exc_info=True
            )
            return PostOutcome(error=_category(error))
        if 200 <= response.status_code < 300:
            return PostOutcome(error=None, body=response.content)
        return PostOutcome(
            error="http_4xx" if response.status_code < 500 else "http_5xx",
            final=response.status_code in FINAL_STATUSES,
        )

    async def challenge(self, *, url: str, secret: str, subscription: str) -> None:
        """Prove the endpoint wants deliveries: it echoes a one-time nonce in a 2xx body."""
        nonce = control_message_id("challenge").removeprefix("msg_challenge_")
        outcome = await self.post(
            url=url,
            secret=secret,
            subscription=subscription,
            message_id=control_message_id("verification"),
            body={"type": "verification", "challenge": nonce},
        )
        if outcome.error is not None:
            raise EventsError(
                ErrorCode.CALLBACK_ENDPOINT_ERROR,
                "the callback endpoint did not answer the challenge",
                {"reason": outcome.error},
            )
        try:
            echoed = json.loads(outcome.body).get("challenge")
        except (ValueError, AttributeError):
            echoed = None
        if not isinstance(echoed, str) or not hmac.compare_digest(echoed, nonce):
            raise EventsError(
                ErrorCode.CALLBACK_ENDPOINT_ERROR,
                "the callback endpoint did not echo the challenge",
                {"reason": "challenge_failed"},
            )
