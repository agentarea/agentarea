"""Background-side `SecretReader` implementation.

Adapters running in the worker's delivery consumer have no request-scoped
DB session or `UserContext`. `LazySecretReader.get_secret` opens a fresh
session per call and resolves the workspace from the id embedded in the
secret name -- a source's credential key (`channel_cred:<slug>:<credential_key>`)
or a task's id -- then delegates to the configured `SecretManagerFactory`.

Implements `SecretReader` (read-only). Set/rotate goes through the
authenticated API path with a real `UserContext`, never through this.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentarea_secrets import SecretManagerFactory

logger = logging.getLogger(__name__)


class LazySecretReader:
    def __init__(self, factory: SecretManagerFactory) -> None:
        self._factory = factory

    async def get_secret(self, name: str) -> str | None:
        from uuid import UUID

        from agentarea_common.auth.context import UserContext
        from agentarea_common.base.tenant_scope import unscoped, workspace_scope
        from agentarea_common.config import get_database
        from agentarea_streams.infrastructure.orm import StreamSourceORM
        from sqlalchemy import select

        database = get_database()
        async with database.async_session_factory() as session:
            # Resolve workspace context from an id embedded in the secret name.
            # Source creds:    "channel_cred:<slug>:<credential_key>"      → StreamSourceORM
            # A2A push tokens: "a2a_push_token:<task_id>:<config_id>"      → TaskORM
            # Task webhooks:   "task_webhook:<task_id>"                     → TaskORM
            user_context: UserContext | None = None
            with unscoped("a background secret read names a source or task; its workspace decides"):
                parts = name.split(":")
                if (name.startswith("a2a_push_token:") and len(parts) >= 3) or (
                    name.startswith("task_webhook:") and len(parts) == 2
                ):
                    try:
                        from agentarea_tasks.infrastructure.orm import TaskORM

                        task_orm = await session.get(TaskORM, UUID(parts[1]))
                        if task_orm:
                            user_context = UserContext(
                                user_id=str(task_orm.created_by),
                                workspace_id=str(task_orm.workspace_id),
                            )
                    except (ValueError, Exception):
                        logger.exception("Failed to resolve task for secret '%s'", name)
                elif name.startswith("channel_cred:") and len(parts) == 3:
                    try:
                        found = await session.execute(
                            select(StreamSourceORM.created_by, StreamSourceORM.workspace_id)
                            .where(StreamSourceORM.credential_key == UUID(parts[2]))
                            .limit(1)
                        )
                        row = found.first()
                        if row:
                            user_context = UserContext(
                                user_id=str(row.created_by), workspace_id=str(row.workspace_id)
                            )
                    except (ValueError, Exception):
                        logger.exception("Failed to resolve the source for secret '%s'", name)

            if not user_context:
                logger.error("Cannot resolve workspace for secret '%s'", name)
                return None

            with workspace_scope(user_context.workspace_id):
                secret_manager = self._factory.create(
                    session=session,
                    user_context=user_context,
                )
                return await secret_manager.get_secret(name)


# Backwards-compat alias for any caller still importing the old name.
LazySecretManager = LazySecretReader
