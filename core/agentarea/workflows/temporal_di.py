"""
Dependency Injection for Temporal Activities

This module provides a clean, declarative way to inject dependencies
into Temporal activities, eliminating the need for manual DI setup
in each activity.

Usage:
    @activity.defn
    async def my_activity(agent_id: str) -> dict[str, Any]:
        deps = await get_activity_deps()
        agent = await deps.agent_repository.get(UUID(agent_id))
        # ... rest of activity logic
"""

import logging
from dataclasses import dataclass
from typing import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession

from agentarea.api.deps.database import get_db_session
from agentarea.common.events.broker import EventBroker
from agentarea.common.events.router import get_event_router, create_event_broker_from_router
from agentarea.common.infrastructure.secret_manager import BaseSecretManager
from agentarea.common.infrastructure.infisical_factory import get_real_secret_manager
from agentarea.common.testing.mocks import TestEventBroker
from agentarea.config import get_settings
from agentarea.modules.agents.infrastructure.repository import AgentRepository
from agentarea.modules.agents.application.agent_builder_service import AgentBuilderService
from agentarea.modules.agents.application.agent_runner_service import AgentRunnerService
from agentarea.modules.llm.application.service import LLMModelInstanceService
from agentarea.modules.llm.infrastructure.llm_model_instance_repository import (
    LLMModelInstanceRepository,
)
from agentarea.modules.mcp.application.service import MCPServerInstanceService
from agentarea.modules.mcp.infrastructure.repository import (
    MCPServerInstanceRepository,
    MCPServerRepository,
)
from agentarea.api.deps.session import InMemorySessionService

logger = logging.getLogger(__name__)


@dataclass
class ActivityDependencies:
    """Container for all dependencies needed by Temporal activities."""

    # Database session
    db_session: AsyncSession

    # Repositories
    agent_repository: AgentRepository
    llm_model_instance_repository: LLMModelInstanceRepository
    mcp_server_instance_repository: MCPServerInstanceRepository
    mcp_server_repository: MCPServerRepository

    # Infrastructure
    event_broker: EventBroker
    secret_manager: BaseSecretManager
    session_service: InMemorySessionService

    # Services
    llm_service: LLMModelInstanceService
    mcp_service: MCPServerInstanceService
    agent_builder: AgentBuilderService
    agent_runner: AgentRunnerService


@asynccontextmanager
async def get_activity_deps() -> AsyncGenerator[ActivityDependencies, None]:
    """
    Get all dependencies needed for Temporal activities.

    This is a single entry point that creates and manages all dependencies
    needed by activities, with proper cleanup and error handling.

    Usage:
        @activity.defn
        async def my_activity(agent_id: str) -> dict[str, Any]:
            async with get_activity_deps() as deps:
                agent = await deps.agent_repository.get(UUID(agent_id))
                # ... rest of activity logic
    """

    async with get_db_session() as db_session:
        try:
            # Create event broker with fallback
            event_broker = await _create_event_broker()

            # Create infrastructure dependencies
            secret_manager = get_real_secret_manager()
            session_service = InMemorySessionService()

            # Create repositories
            agent_repository = AgentRepository(db_session)
            llm_model_instance_repository = LLMModelInstanceRepository(db_session)
            mcp_server_instance_repository = MCPServerInstanceRepository(db_session)
            mcp_server_repository = MCPServerRepository(db_session)

            # Create services
            llm_service = LLMModelInstanceService(
                repository=llm_model_instance_repository,
                event_broker=event_broker,
                secret_manager=secret_manager,
            )

            mcp_service = MCPServerInstanceService(
                repository=mcp_server_instance_repository,
                event_broker=event_broker,
                mcp_server_repository=mcp_server_repository,
                secret_manager=secret_manager,
            )

            agent_builder = AgentBuilderService(
                repository=agent_repository,
                event_broker=event_broker,
                llm_model_instance_service=llm_service,
                mcp_server_instance_service=mcp_service,
            )

            agent_runner = AgentRunnerService(
                repository=agent_repository,
                event_broker=event_broker,
                llm_model_instance_service=llm_service,
                session_service=session_service,
                agent_builder_service=agent_builder,
                agent_communication_service=None,  # Not needed for basic task execution
            )

            # Create the dependencies container
            deps = ActivityDependencies(
                db_session=db_session,
                agent_repository=agent_repository,
                llm_model_instance_repository=llm_model_instance_repository,
                mcp_server_instance_repository=mcp_server_instance_repository,
                mcp_server_repository=mcp_server_repository,
                event_broker=event_broker,
                secret_manager=secret_manager,
                session_service=session_service,
                llm_service=llm_service,
                mcp_service=mcp_service,
                agent_builder=agent_builder,
                agent_runner=agent_runner,
            )

            logger.debug("Created activity dependencies successfully")
            yield deps

        except Exception as e:
            logger.error(f"Failed to create activity dependencies: {e}")
            raise


async def _create_event_broker() -> EventBroker:
    """Create event broker with fallback to test broker."""
    try:
        settings = get_settings()
        router = get_event_router(settings.broker)
        event_broker = create_event_broker_from_router(router)
        logger.debug(f"Created Redis event broker: {type(event_broker).__name__}")
        return event_broker
    except Exception as e:
        logger.warning(f"Failed to create Redis event broker: {e}. Using TestEventBroker fallback.")
        return TestEventBroker()


# Convenience functions for common use cases
async def get_agent_builder() -> AgentBuilderService:
    """Get just the agent builder service for validation activities."""
    async with get_activity_deps() as deps:
        return deps.agent_builder


async def get_agent_runner() -> AgentRunnerService:
    """Get just the agent runner service for execution activities."""
    async with get_activity_deps() as deps:
        return deps.agent_runner
