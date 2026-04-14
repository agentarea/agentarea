"""Lazy secret manager that opens a fresh DB session per get_secret call.

Used by background subscribers (ChannelEventSubscriber) that don't have a
request-scoped DB session or user context. Resolves workspace context from
the trigger_id embedded in the secret name pattern: channel_cred:<type>:<trigger_id>.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentarea_secrets import SecretManagerFactory

logger = logging.getLogger(__name__)


class LazySecretManager:
    """BaseSecretManager adapter that resolves workspace from the secret name."""

    def __init__(self, factory: SecretManagerFactory) -> None:
        self._factory = factory

    async def get_secret(self, name: str) -> str | None:
        from uuid import UUID

        from agentarea_common.auth.context import UserContext
        from agentarea_common.config import get_database
        from agentarea_triggers.infrastructure.orm import TriggerORM

        database = get_database()
        async with database.async_session_factory() as session:
            # Resolve workspace context from trigger_id in the secret name.
            # Secret name pattern: "channel_cred:<channel_type>:<trigger_id>"
            user_context: UserContext | None = None
            parts = name.split(":")
            if len(parts) >= 3:
                try:
                    trigger_id = UUID(parts[-1])
                    trigger_orm = await session.get(TriggerORM, trigger_id)
                    if trigger_orm:
                        user_context = UserContext(
                            user_id=str(trigger_orm.created_by),
                            workspace_id=str(trigger_orm.workspace_id),
                        )
                except (ValueError, Exception):
                    logger.exception("Failed to resolve trigger for secret '%s'", name)

            if not user_context:
                logger.error("Cannot resolve workspace for secret '%s'", name)
                return None

            secret_manager = self._factory.create(
                session=session,
                user_context=user_context,
            )
            return await secret_manager.get_secret(name)

    async def set_secret(self, name: str, value: str) -> None:
        raise NotImplementedError("LazySecretManager is read-only")

    async def delete_secret(self, name: str) -> None:
        raise NotImplementedError("LazySecretManager is read-only")
