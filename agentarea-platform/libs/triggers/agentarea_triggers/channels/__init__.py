"""Channel adapters for outbound message delivery."""

from typing import Any, Protocol


class ChannelAdapter(Protocol):
    """Protocol for bidirectional channel adapters.

    Each adapter knows how to format workflow events for its channel
    and deliver messages to the correct destination.
    """

    def format(self, event: dict[str, Any], presentation: str) -> str:
        """Format a workflow event for this channel.

        Args:
            event: Workflow event dict (type, data, task_id, etc.)
            presentation: Presentation mode (concise, summary, silent).

        Returns:
            Formatted message string ready to send.
        """
        ...

    async def send(self, channel_config: dict[str, Any], message: str) -> None:
        """Send a formatted message to the channel destination.

        Args:
            channel_config: Channel-specific routing info (chat_id, reply_to, etc.)
            message: Pre-formatted message string.
        """
        ...


# Registry of available channel adapters
_ADAPTERS: dict[str, ChannelAdapter] = {}


def register_adapter(name: str, adapter: ChannelAdapter) -> None:
    """Register a channel adapter instance."""
    _ADAPTERS[name] = adapter


def get_adapter(name: str) -> ChannelAdapter | None:
    """Get a registered adapter by channel type name."""
    return _ADAPTERS.get(name)


def list_adapters() -> list[str]:
    """List all registered adapter names."""
    return list(_ADAPTERS.keys())


class WebhookRegistrar(Protocol):
    """A channel that registers its inbound webhook with its provider.

    Segregated from ChannelAdapter (outbound delivery) on purpose: only channels
    whose provider *pushes* updates to a registered URL implement this. Polling
    or gateway channels (e.g. Discord) simply have no registrar, and the
    orchestrating service treats their absence as a no-op.
    """

    async def register(
        self, *, webhook_url: str, credentials: dict[str, Any], secret_token: str | None = None
    ) -> bool:
        """Point the provider at ``webhook_url`` for this bot. Returns success."""
        ...

    async def deregister(self, *, credentials: dict[str, Any]) -> None:
        """Clear the provider-side webhook for this bot."""
        ...


# Registry of inbound webhook registrars, keyed by channel type — mirrors _ADAPTERS.
_WEBHOOK_REGISTRARS: dict[str, WebhookRegistrar] = {}


def register_webhook_registrar(name: str, registrar: WebhookRegistrar) -> None:
    """Register a webhook registrar for a channel type."""
    _WEBHOOK_REGISTRARS[name] = registrar


def get_webhook_registrar(name: str) -> WebhookRegistrar | None:
    """Get a registered webhook registrar by channel type name."""
    return _WEBHOOK_REGISTRARS.get(name)


def list_webhook_registrars() -> list[str]:
    """List channel types that support inbound webhook registration."""
    return list(_WEBHOOK_REGISTRARS.keys())


# Import builtin channel modules so their registrars self-register on package
# import. Kept at the bottom so the registry callables above already exist; there
# is no circular import because telegram only needs the names defined here.
from . import telegram  # noqa: E402,F401
