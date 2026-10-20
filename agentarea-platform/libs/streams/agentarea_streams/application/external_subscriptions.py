"""MCP Events webhook subscribers of a stream: ``events/subscribe`` and ``events/unsubscribe``.

A subscriber is an ``EXTERNAL`` stream subscription keyed by (principal,
callback URL, stream, arguments). Its ``whsec_`` secret lives in the secret
store under ``secret_name(external_id)`` and leaves with it, on unsubscribe,
on expiry (the delivery sweeper) and with its stream. Before the first delivery
to a (principal, URL) the endpoint must echo a challenge. Never commits.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from ..domain.errors import ExternalSubscriptionLimitError
from ..domain.mcp_events import (
    MAX_SUBSCRIPTIONS_PER_WORKSPACE,
    ErrorCode,
    EventArguments,
    EventsError,
    grant_refresh_before,
    subscription_id,
    validate_secret,
)
from .stream_service import StreamService


def secret_name(external_id: str) -> str:
    """Where a subscriber's signing secret is stored."""
    return f"mcp_events_whsec:{external_id}"


class SecretStore(Protocol):
    async def set_secret(self, secret_name: str, secret_value: str) -> None: ...

    async def delete_secret(self, secret_name: str) -> bool: ...


class CallbackEndpoint(Protocol):
    async def check(self, url: str) -> None: ...

    async def challenge(self, *, url: str, secret: str, subscription: str) -> None: ...


@dataclass(frozen=True)
class Subscribed:
    id: str
    refresh_before: datetime
    #: Present on a refresh of an existing subscriber.
    delivery_status: dict[str, Any] | None


def _utcnow() -> datetime:
    return datetime.now(UTC)


class ExternalSubscriptions:
    def __init__(
        self,
        streams: StreamService,
        secrets: SecretStore,
        endpoint: CallbackEndpoint,
        *,
        clock: Callable[[], datetime] = _utcnow,
    ):
        self._streams = streams
        self._secrets = secrets
        self._endpoint = endpoint
        self._clock = clock

    async def subscribe(
        self,
        *,
        stream_id: UUID,
        subscriber: str,
        url: str,
        secret: str,
        arguments: EventArguments,
        ttl_ms: int | None,
    ) -> Subscribed:
        validate_secret(secret)
        await self._endpoint.check(url)
        external_id = subscription_id(subscriber, url, stream_id, arguments)
        existing = await self._streams.external_subscription(external_id)
        status = _delivery_status(existing) if existing is not None else None
        now = self._clock()
        if existing is None and not await self._streams.endpoint_verified(subscriber, url):
            await self._endpoint.challenge(url=url, secret=secret, subscription=external_id)
        name = secret_name(external_id)
        await self._secrets.set_secret(name, secret)
        refresh_before = grant_refresh_before(ttl_ms, now=now)
        try:
            await self._streams.subscribe_external(
                stream_id=stream_id,
                event_filter=arguments.to_filter(),
                external_id=external_id,
                subscriber=subscriber,
                callback_url=url,
                secret_name=name,
                expires_at=refresh_before,
                verified_at=now,
                limit=MAX_SUBSCRIPTIONS_PER_WORKSPACE,
            )
        except ExternalSubscriptionLimitError as error:
            raise EventsError(
                ErrorCode.RESOURCE_EXHAUSTED,
                str(error),
                {"limit": "subscriptions", "max": error.limit},
            ) from error
        return Subscribed(id=external_id, refresh_before=refresh_before, delivery_status=status)

    async def unsubscribe(
        self, *, stream_id: UUID, subscriber: str, url: str, arguments: EventArguments
    ) -> None:
        external_id = subscription_id(subscriber, url, stream_id, arguments)
        subscription = await self._streams.external_subscription(external_id)
        if subscription is None:
            raise EventsError(ErrorCode.NOT_FOUND, "no such subscription", {"kind": "subscription"})
        await self._streams.unsubscribe_external(subscription)
        await self._secrets.delete_secret(secret_name(external_id))


async def release_subscriber_secrets(
    streams: StreamService, secrets: SecretStore, stream_id: UUID
) -> None:
    """Drop the secrets of a stream's subscribers before the stream, and they, go."""
    for subscription in await streams.external_subscriptions(stream_id):
        if subscription.external_id:
            await secrets.delete_secret(secret_name(subscription.external_id))


def _delivery_status(subscription: Any) -> dict[str, Any]:
    status: dict[str, Any] = {
        "active": subscription.status == "active",
        "lastDeliveryAt": _iso(subscription.last_delivery_at),
        "lastError": subscription.last_error,
    }
    if subscription.failed_since is not None:
        status["failedSince"] = _iso(subscription.failed_since)
    return status


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None
