"""Base class for platform toolsets that need per-request service creation.

Handles the boilerplate of:
1. Getting UserContext from MCP ContextVar
2. Creating a DB session
3. Building RepositoryFactory(session, user_context)
4. Creating the service instance
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from agentarea_common.auth.context import UserContext
from agentarea_common.base.repository_factory import RepositoryFactory
from agentarea_common.events.broker import EventBroker
from agentarea_common.infrastructure.secret_manager import BaseSecretManager
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


@asynccontextmanager
async def platform_context() -> AsyncIterator[
    tuple[AsyncSession, UserContext, RepositoryFactory, EventBroker, BaseSecretManager]
]:
    """Create a per-request platform context for tool execution.

    Yields (session, user_context, repository_factory, event_broker, secret_manager).
    Session is committed on success, rolled back on error.
    """
    from agentarea_agents_sdk.mcp_server.auth import get_mcp_user_context
    from agentarea_common.infrastructure.connection_manager import get_connection_manager
    from agentarea_common.infrastructure.database import db
    from agentarea_secrets.secret_manager_factory import get_real_secret_manager

    user_context = get_mcp_user_context()
    connection_manager = get_connection_manager()
    event_broker = await connection_manager.get_event_broker()

    async with db.session() as session:
        repo_factory = RepositoryFactory(session, user_context)
        secret_manager = get_real_secret_manager(session=session, user_context=user_context)

        yield session, user_context, repo_factory, event_broker, secret_manager

        await session.commit()
