"""
Service dependencies for FastAPI endpoints.

This module provides dependency injection functions for services
used across the AgentArea API endpoints.
"""

import logging
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from agentarea.common.events.broker import EventBroker
from agentarea.common.events.router import get_event_router, create_event_broker_from_router
from agentarea.common.infrastructure.database import get_db_session
from agentarea.common.infrastructure.secret_manager import BaseSecretManager
from agentarea.common.infrastructure.infisical_factory import get_real_secret_manager
from agentarea.config import get_settings
from agentarea.modules.tasks.infrastructure.repository import SQLAlchemyTaskRepository
from agentarea.modules.tasks.task_service import TaskService
from agentarea.modules.tasks.task_manager import BaseTaskManager
# from agentarea.modules.tasks.database_task_manager import DatabaseTaskManager  # TODO: Fix implementation
from agentarea.modules.chat.unified_chat_service import UnifiedTaskService
from agentarea.modules.agents.application.agent_service import AgentService
from agentarea.modules.agents.infrastructure.repository import AgentRepository
from agentarea.modules.llm.application.llm_model_service import LLMModelService
from agentarea.modules.llm.application.service import LLMModelInstanceService
from agentarea.modules.llm.infrastructure.llm_model_repository import LLMModelRepository
from agentarea.modules.llm.infrastructure.llm_model_instance_repository import LLMModelInstanceRepository
# LLM execution happens in agent_runner_service via Google ADK, not here
from agentarea.modules.mcp.application.service import MCPServerService, MCPServerInstanceService
from agentarea.modules.mcp.infrastructure.repository import MCPServerRepository, MCPServerInstanceRepository
from agentarea.modules.agents.application.workflow_task_execution_service import WorkflowTaskExecutionService

logger = logging.getLogger(__name__)


async def get_event_broker() -> EventBroker:
    """Get EventBroker instance - real Redis implementation."""
    try:
        settings = get_settings()
        router = get_event_router(settings.broker)
        event_broker = create_event_broker_from_router(router)
        logger.info(f"Created Redis event broker: {type(event_broker).__name__}")
        return event_broker
    except Exception as e:
        logger.warning(f"Failed to create Redis event broker: {e}. Falling back to in-memory implementation.")
        # Fallback to in-memory implementation for development
        from agentarea.common.testing.mocks import TestEventBroker
        test_broker = TestEventBroker()
        logger.info(f"Using TestEventBroker fallback: {type(test_broker).__name__}")
        return test_broker


async def get_secret_manager() -> BaseSecretManager:
    """Get SecretManager instance - real Infisical implementation."""
    return get_real_secret_manager()


async def get_task_repository(db: Annotated[AsyncSession, Depends(get_db_session)]):
    """
    Get a TaskRepository instance for the current request.
    
    Uses a new database session for each request to ensure transaction isolation.
    """
    return SQLAlchemyTaskRepository(db)


# Shared task manager instance
_task_manager_instance: BaseTaskManager | None = None

async def get_database_task_manager(
    task_repository: Annotated[SQLAlchemyTaskRepository, Depends(get_task_repository)],
    event_broker: Annotated[EventBroker, Depends(get_event_broker)]
) -> BaseTaskManager:
    """
    Get a real database-backed TaskManager instance.
    
    This replaces the in-memory task manager with real persistence.
    Note: DatabaseTaskManager is still under development.
    """
    global _task_manager_instance
    
    # Use a shared instance to maintain task state across requests
    if _task_manager_instance is None:
        from agentarea.modules.tasks.in_memory_task_manager import InMemoryTaskManager
        _task_manager_instance = InMemoryTaskManager()
        logger.info("Created shared InMemoryTaskManager instance")
    
    return _task_manager_instance


async def get_task_service(
    event_broker: Annotated[EventBroker, Depends(get_event_broker)],
    task_repository: Annotated[SQLAlchemyTaskRepository, Depends(get_task_repository)]
):
    """
    Get a TaskService instance for the current request.
    
    Combines the global EventBroker singleton with a request-scoped TaskRepository.
    """
    return TaskService(event_broker=event_broker, task_repository=task_repository)


async def get_unified_chat_service():
    """
    Get a UnifiedTaskService instance for the current request.
    
    Returns a new instance for each request with protocol adapters.
    """
    return UnifiedTaskService()


async def get_agent_repository(db: Annotated[AsyncSession, Depends(get_db_session)]):
    """
    Get an AgentRepository instance for the current request.
    """
    return AgentRepository(db)


async def get_agent_service(
    event_broker: Annotated[EventBroker, Depends(get_event_broker)],
    agent_repository: Annotated[AgentRepository, Depends(get_agent_repository)]
):
    """
    Get an AgentService instance for the current request.
    
    Returns a new instance for each request.
    """
    return AgentService(repository=agent_repository, event_broker=event_broker)


async def get_workflow_task_execution_service():
    """
    Get a WorkflowTaskExecutionService instance for the current request.
    
    This service uses Temporal workflows for non-blocking task execution.
    """
    return WorkflowTaskExecutionService()


# LLM Services
async def get_llm_model_repository(db: Annotated[AsyncSession, Depends(get_db_session)]):
    """Get a LLMModelRepository instance for the current request."""
    return LLMModelRepository(db)


async def get_llm_model_service(
    event_broker: Annotated[EventBroker, Depends(get_event_broker)],
    llm_model_repository: Annotated[LLMModelRepository, Depends(get_llm_model_repository)]
):
    """Get a LLMModelService instance for the current request."""
    return LLMModelService(repository=llm_model_repository, event_broker=event_broker)


async def get_llm_model_instance_repository(db: Annotated[AsyncSession, Depends(get_db_session)]):
    """Get a LLMModelInstanceRepository instance for the current request."""
    return LLMModelInstanceRepository(db)


async def get_llm_model_instance_service(
    event_broker: Annotated[EventBroker, Depends(get_event_broker)],
    llm_model_instance_repository: Annotated[LLMModelInstanceRepository, Depends(get_llm_model_instance_repository)],
    secret_manager: Annotated[BaseSecretManager, Depends(get_secret_manager)]
):
    """Get a LLMModelInstanceService instance for the current request."""
    return LLMModelInstanceService(
        repository=llm_model_instance_repository,
        event_broker=event_broker,
        secret_manager=secret_manager
    )


# LLM execution removed - handled by agent_runner_service via Google ADK


# MCP Services
async def get_mcp_server_repository(db: Annotated[AsyncSession, Depends(get_db_session)]):
    """Get a MCPServerRepository instance for the current request."""
    return MCPServerRepository(db)


async def get_mcp_server_service(
    event_broker: Annotated[EventBroker, Depends(get_event_broker)],
    mcp_server_repository: Annotated[MCPServerRepository, Depends(get_mcp_server_repository)]
):
    """Get a MCPServerService instance for the current request."""
    return MCPServerService(repository=mcp_server_repository, event_broker=event_broker)


async def get_mcp_server_instance_repository(db: Annotated[AsyncSession, Depends(get_db_session)]):
    """Get a MCPServerInstanceRepository instance for the current request."""
    return MCPServerInstanceRepository(db)


async def get_mcp_server_instance_service(
    event_broker: Annotated[EventBroker, Depends(get_event_broker)],
    mcp_server_instance_repository: Annotated[MCPServerInstanceRepository, Depends(get_mcp_server_instance_repository)],
    mcp_server_repository: Annotated[MCPServerRepository, Depends(get_mcp_server_repository)],
    secret_manager: Annotated[BaseSecretManager, Depends(get_secret_manager)]
):
    """Get a MCPServerInstanceService instance for the current request."""
    return MCPServerInstanceService(
        repository=mcp_server_instance_repository,
        event_broker=event_broker,
        mcp_server_repository=mcp_server_repository,
        secret_manager=secret_manager
    )


