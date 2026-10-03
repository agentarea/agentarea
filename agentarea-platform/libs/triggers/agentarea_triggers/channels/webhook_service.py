"""Application service that registers/clears inbound channel webhooks.

Thin orchestrator over the WebhookRegistrar registry: resolve the registrar for
a channel type, build the platform webhook URL from an injected base URL, and
delegate. No channel-specific knowledge lives here or in the HTTP controller —
adding a channel is a new registrar plus one ``register_webhook_registrar`` call.
"""

from __future__ import annotations

import logging
from typing import Any

from . import get_webhook_registrar

logger = logging.getLogger(__name__)


class ChannelWebhookService:
    """Register/deregister a trigger's provider-side webhook."""

    def __init__(self, base_url: str | None):
        # The reachable ingress Telegram (etc.) should POST to. May differ from
        # the API host; empty disables registration.
        self._base = (base_url or "").rstrip("/")

    @staticmethod
    def _channel_name(channel_type: Any) -> str:
        return channel_type.value if hasattr(channel_type, "value") else str(channel_type or "")

    def _webhook_url(self, webhook_id: str | None) -> str | None:
        if not (self._base and webhook_id):
            return None
        return f"{self._base}/webhooks/{webhook_id}"

    async def register(
        self,
        *,
        channel_type: Any,
        webhook_id: str | None,
        credentials: dict[str, Any] | None,
        secret_token: str | None = None,
    ) -> bool | None:
        """Point the provider at this trigger's webhook URL.

        True when the provider accepted it, False when it refused or could not
        be reached, None when there is nothing to register (the channel has no
        provider-side webhook, or no public base URL is configured). Callers
        must not persist anything the provider needs to agree on -- such as a
        Telegram secret token -- on False.
        """
        registrar = get_webhook_registrar(self._channel_name(channel_type))
        url = self._webhook_url(webhook_id)
        if not (registrar and url):
            return None
        return await registrar.register(
            webhook_url=url, credentials=credentials or {}, secret_token=secret_token
        )

    async def deregister(self, *, channel_type: Any, credentials: dict[str, Any] | None) -> None:
        registrar = get_webhook_registrar(self._channel_name(channel_type))
        if registrar:
            await registrar.deregister(credentials=credentials or {})
