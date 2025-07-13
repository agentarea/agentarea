"""Service dependencies for FastAPI endpoints.

This module provides dependency injection functions for services
used across the AgentArea API endpoints.
"""

import logging
from typing import Annotated

from agentarea_agents.application.agent_service import AgentService
from agentarea_agents.application.execution_service import ExecutionService
from agentarea_agents.application.temporal_workflow_service import (
    TemporalWorkflowService,
)
from agentarea_agents.domain.interfaces import ExecutionServiceInterface
from agentarea_agents.infrastructure.repository import AgentRepository

# from agentarea_tasks.database_task_manager import DatabaseTaskManager
# TODO: Fix implementation
from agentarea_common.config import get_settings
from agentarea_common.events.broker import EventBroker
from agentarea_common.events.router import get_event_router
from agentarea_common.infrastructure.database import get_db_session
from agentarea_common.infrastructure.infisical_factory import get_real_secret_manager
from agentarea_common.infrastructure.secret_manager import BaseSecretManager
from agentarea_llm.application.model_instance_service import ModelInstanceService
from agentarea_llm.application.provider_service import ProviderService
from agentarea_llm.infrastructure.model_instance_repository import ModelInstanceRepository
from agentarea_llm.infrastructure.model_spec_repository import ModelSpecRepository
from agentarea_llm.infrastructure.provider_config_repository import ProviderConfigRepository
from agentarea_llm.infrastructure.provider_spec_repository import ProviderSpecRepository

# LLM execution happens in agent_runner_service via Google ADK, not here
from agentarea_mcp.application.service import MCPServerInstanceService, MCPServerService
from agentarea_mcp.infrastructure.repository import (
    MCPServerInstanceRepository,
    MCPServerRepository,
)
from agentarea_tasks.infrastructure.repository import TaskRepository
from agentarea_tasks.task_manager import BaseTaskManager
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Common database dependency
DatabaseSessionDep = Annotated[AsyncSession, Depends(get_db_session)]

# Common event broker dependency
EventBrokerDep = Annotated[EventBroker, Depends(get_event_router)]

# Secret Manager dependencies
BaseSecretManagerDep = Annotated[BaseSecretManager, Depends(get_real_secret_manager)]


# Agent Service dependencies
async def get_agent_service(
    db_session: DatabaseSessionDep,
    secret_manager: BaseSecretManagerDep,
) -> AgentService:
    """Get an AgentService instance for the current request."""
    repository = AgentRepository(db_session)
    return AgentService(repository, secret_manager)


# LLM Service dependencies
async def get_provider_service(
    db_session: DatabaseSessionDep,
    secret_manager: BaseSecretManagerDep,
) -> ProviderService:
    """Get a ProviderService instance for the current request."""
    provider_config_repository = ProviderConfigRepository(db_session)
    provider_spec_repository = ProviderSpecRepository(db_session)
    return ProviderService(provider_config_repository, provider_spec_repository, secret_manager)


async def get_model_instance_service(
    db_session: DatabaseSessionDep,
    secret_manager: BaseSecretManagerDep,
) -> ModelInstanceService:
    """Get a ModelInstanceService instance for the current request."""
    model_instance_repository = ModelInstanceRepository(db_session)
    model_spec_repository = ModelSpecRepository(db_session)
    return ModelInstanceService(model_instance_repository, model_spec_repository, secret_manager)


# Task Service dependencies
async def get_task_repository(db_session: DatabaseSessionDep) -> TaskRepository:
    """Get a TaskRepository instance for the current request."""
    return TaskRepository(db_session)


async def get_task_manager(
    task_repository: TaskRepository = Depends(get_task_repository),
) -> BaseTaskManager:
    """Get a BaseTaskManager instance for the current request."""
    # This is a placeholder implementation
    # TODO: Replace with actual task manager implementation when available
    from agentarea_tasks.in_memory_task_manager import InMemoryTaskManager

    return InMemoryTaskManager(task_repository)


async def get_temporal_workflow_service():
    """Get a TemporalWorkflowService instance for the current request.

    This service uses Temporal workflows for non-blocking task execution.
    """
    execution_service = await get_execution_service()
    return TemporalWorkflowService(execution_service)

async def get_execution_service() -> ExecutionServiceInterface:
    settings = get_settings()
    from agentarea_agents.infrastructure.temporal_orchestrator import TemporalWorkflowOrchestrator
    temporal_orchestrator = TemporalWorkflowOrchestrator(
        temporal_address=settings.workflow.TEMPORAL_SERVER_URL,
        task_queue=settings.workflow.TEMPORAL_TASK_QUEUE,
        max_concurrent_activities=settings.workflow.TEMPORAL_MAX_CONCURRENT_ACTIVITIES,
        max_concurrent_workflows=settings.workflow.TEMPORAL_MAX_CONCURRENT_WORKFLOWS,
    )
    execution_service = ExecutionService(temporal_orchestrator)
    """Get an execution service instance for the current request."""
    return execution_service


# MCP Service dependencies
async def get_mcp_server_service(
    db_session: DatabaseSessionDep,
    secret_manager: BaseSecretManagerDep,
) -> MCPServerService:
    """Get a MCPServerService instance for the current request."""
    repository = MCPServerRepository(db_session)
    return MCPServerService(repository, secret_manager)


async def get_mcp_server_instance_service(
    db_session: DatabaseSessionDep,
    secret_manager: BaseSecretManagerDep,
) -> MCPServerInstanceService:
    """Get a MCPServerInstanceService instance for the current request."""
    repository = MCPServerInstanceRepository(db_session)
    return MCPServerInstanceService(repository, secret_manager)


# Common service type hints for easier use
AgentServiceDep = Annotated[AgentService, Depends(get_agent_service)]
ProviderServiceDep = Annotated[ProviderService, Depends(get_provider_service)]
ModelInstanceServiceDep = Annotated[ModelInstanceService, Depends(get_model_instance_service)]
TaskRepositoryDep = Annotated[TaskRepository, Depends(get_task_repository)]
TaskManagerDep = Annotated[BaseTaskManager, Depends(get_task_manager)]
TemporalWorkflowServiceDep = Annotated[TemporalWorkflowService, Depends(get_temporal_workflow_service)]
MCPServerServiceDep = Annotated[MCPServerService, Depends(get_mcp_server_service)]
MCPServerInstanceServiceDep = Annotated[MCPServerInstanceService, Depends(get_mcp_server_instance_service)]


# Backward compatibility aliases for old function names
get_llm_model_service = get_model_instance_service
get_llm_model_instance_service = get_model_instance_service
get_mcp_server_service = get_mcp_server_service
get_mcp_server_instance_service = get_mcp_server_instance_service


# Additional backward compatibility functions
async def get_model_spec_repository(db_session: DatabaseSessionDep) -> ModelSpecRepository:
    """Get a ModelSpecRepository instance for the current request."""
    return ModelSpecRepository(db_session)


async def get_event_broker() -> EventBroker:
    """Get EventBroker instance - real Redis implementation."""
    try:
        settings = get_settings()
        from agentarea_common.events.router import create_event_broker_from_router
        router = get_event_router(settings.broker)
        event_broker = create_event_broker_from_router(router)
        logger.info(f"Created Redis event broker: {type(event_broker).__name__}")
        return event_broker
    except Exception as e:
        logger.error(f"Failed to create Redis event broker: {e}")
        raise e


async def get_secret_manager() -> BaseSecretManager:
    """Get SecretManager instance - real Infisical implementation."""
    return get_real_secret_manager()
