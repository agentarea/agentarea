"""Dependency injection for Temporal activities.

This module provides a clean DI system for activities, similar to FastAPI's approach.
Activities should only work with services, not manually create sessions or contexts.
"""

import logging
from typing import Any

from agentarea_agents.application.agent_service import AgentService
from agentarea_common.auth.context import UserContext
from agentarea_common.base import RepositoryFactory
from agentarea_common.config import get_database
from agentarea_llm.application.model_instance_service import ModelInstanceService
from agentarea_llm.infrastructure.model_instance_repository import ModelInstanceRepository
from agentarea_mcp.application.service import MCPServerInstanceService
from agentarea_tasks.application.task_event_service import TaskEventService

from ..interfaces import ActivityDependencies

logger = logging.getLogger(__name__)


class ActivityServiceContainer:
    """Service container for Temporal activities.
    
    Provides clean service access without manual session/context management.
    """

    def __init__(self, dependencies: ActivityDependencies):
        self.dependencies = dependencies
        self._database = get_database()

    async def get_agent_service(self, user_context: UserContext) -> tuple[AgentService, Any]:
        """Get AgentService with proper session and context."""
        session = self._database.async_session_factory()
        repository_factory = RepositoryFactory(session, user_context)
        service = AgentService(
            repository_factory=repository_factory,
            event_broker=self.dependencies.event_broker
        )
        return service, session

    async def get_model_instance_service(self, user_context: UserContext) -> tuple[ModelInstanceService, Any]:
        """Get ModelInstanceService with proper session and context."""
        session = self._database.async_session_factory()
        repository = ModelInstanceRepository(session, user_context)
        service = ModelInstanceService(
            repository=repository,
            event_broker=self.dependencies.event_broker,
            secret_manager=self.dependencies.secret_manager
        )
        return service, session

    async def get_mcp_server_instance_service(self, user_context: UserContext) -> tuple[MCPServerInstanceService, Any]:
        """Get MCPServerInstanceService with proper session and context."""
        session = self._database.async_session_factory()
        repository_factory = RepositoryFactory(session, user_context)
        service = MCPServerInstanceService(
            repository_factory=repository_factory,
            event_broker=self.dependencies.event_broker,
            secret_manager=self.dependencies.secret_manager
        )
        return service, session

    async def get_task_event_service(self, user_context: UserContext) -> tuple[TaskEventService, Any]:
        """Get TaskEventService with proper session and context."""
        session = self._database.async_session_factory()
        repository_factory = RepositoryFactory(session, user_context)
        service = TaskEventService(
            repository_factory=repository_factory,
            event_broker=self.dependencies.event_broker
        )
        return service, session


def create_user_context(user_context_data: dict[str, Any]) -> UserContext:
    """Helper to create UserContext from data dictionary."""
    return UserContext(
        user_id=user_context_data.get("user_id", "system"),
        workspace_id=user_context_data["workspace_id"]
    )


def create_system_context(workspace_id: str) -> UserContext:
    """Helper to create system context for background tasks."""
    return UserContext(
        user_id="system",
        workspace_id=workspace_id
    )


class ActivityContext:
    """Context manager for activity execution with proper cleanup."""

    def __init__(self, container: ActivityServiceContainer, user_context: UserContext, auto_commit: bool = True):
        self.container = container
        self.user_context = user_context
        self.auto_commit = auto_commit
        self._sessions = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        # Handle commits/rollbacks first
        for session in self._sessions:
            try:
                if exc_type is None and self.auto_commit:
                    # No exception occurred, commit the transaction
                    await session.commit()
                else:
                    # Exception occurred or auto_commit disabled, rollback
                    await session.rollback()
            except Exception as e:
                logger.warning(f"Failed to commit/rollback session: {e}")

        # Clean up sessions
        for session in self._sessions:
            try:
                await session.close()
            except Exception as e:
                logger.warning(f"Failed to close session: {e}")

    async def get_agent_service(self) -> AgentService:
        """Get AgentService for this context."""
        service, session = await self.container.get_agent_service(self.user_context)
        self._sessions.append(session)
        return service

    async def get_model_instance_service(self) -> ModelInstanceService:
        """Get ModelInstanceService for this context."""
        service, session = await self.container.get_model_instance_service(self.user_context)
        self._sessions.append(session)
        return service

    async def get_mcp_server_instance_service(self) -> MCPServerInstanceService:
        """Get MCPServerInstanceService for this context."""
        service, session = await self.container.get_mcp_server_instance_service(self.user_context)
        self._sessions.append(session)
        return service

    async def get_task_event_service(self) -> TaskEventService:
        """Get TaskEventService for this context."""
        service, session = await self.container.get_task_event_service(self.user_context)
        self._sessions.append(session)
        return service

    async def commit(self):
        """Manually commit all sessions in this context."""
        for session in self._sessions:
            try:
                await session.commit()
            except Exception as e:
                logger.error(f"Failed to commit session: {e}")
                raise

    async def rollback(self):
        """Manually rollback all sessions in this context."""
        for session in self._sessions:
            try:
                await session.rollback()
            except Exception as e:
                logger.warning(f"Failed to rollback session: {e}")
