"""Shared mock implementations for testing.

This module consolidates all the duplicated Simple/Mock implementations
scattered across the codebase into a single shared location.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from agentarea_common.events.base_events import DomainEvent, EventEnvelope
from agentarea_common.events.broker import EventBroker
from agentarea_common.infrastructure.secret_manager import BaseSecretManager

if TYPE_CHECKING:
    from agentarea_common.events.event_models import BaseEvent

logger = logging.getLogger(__name__)


class TestEventBroker(EventBroker):
    """Simple event broker for testing.

    Consolidates all the SimpleEventBroker/TestEventBroker implementations
    from various test files into a single shared implementation.
    """

    def __init__(self):
        self.published_events: list[object] = []

    async def publish(self, event: DomainEvent | EventEnvelope | BaseEvent) -> None:
        """Store published events for test verification.

        We intentionally keep the event object as-is to allow tests to assert
        identity/equality with mock events or legacy DomainEvent instances.
        """
        self.published_events.append(event)
        logger.debug("Test Event Published: %s", event)

    def get_published_events(self) -> list[object]:
        """Get all published events for test assertions."""
        return self.published_events.copy()

    def clear_events(self) -> None:
        """Clear all published events."""
        self.published_events.clear()


class TestSecretManager(BaseSecretManager):
    """Simple secret manager for testing.

    Consolidates all the MockSecretManager/SimpleSecretManager/TestSecretManager
    implementations from various files into a single shared implementation.
    """

    def __init__(self):
        self._secrets: dict[str, str] = {}

    async def get_secret(self, secret_name: str) -> str | None:
        """Get a secret value."""
        return self._secrets.get(secret_name)

    async def set_secret(self, secret_name: str, secret_value: str) -> None:
        """Set a secret value."""
        self._secrets[secret_name] = secret_value
        logger.debug("Test Secret Set: %s", secret_name)

    async def delete_secret(self, secret_name: str) -> bool:
        """Delete a secret and return True if it existed."""
        return self._secrets.pop(secret_name, None) is not None

    def get_all_secrets(self) -> dict[str, str]:
        """Get all secrets for test verification."""
        return self._secrets.copy()

    def clear_secrets(self) -> None:
        """Clear all secrets."""
        self._secrets.clear()


# Backward compatibility aliases for existing code
SimpleEventBroker = TestEventBroker
MockSecretManager = TestSecretManager
SimpleSecretManager = TestSecretManager
