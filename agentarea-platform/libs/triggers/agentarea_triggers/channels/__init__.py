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
