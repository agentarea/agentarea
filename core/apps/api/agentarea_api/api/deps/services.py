"""Service dependencies for FastAPI endpoints.

This module provides dependency injection functions for services
used across the AgentArea API endpoints.
"""

import logging
from datetime import datetime
from typing import Annotated

from agentarea_agents.application.agent_service import AgentService
from agentarea_agents.application.temporal_workflow_service import TemporalWorkflowService
from agentarea_agents.domain.interfaces import ExecutionServiceInterface
from agentarea_common.auth import UserContextDep
from agentarea_common.base import RepositoryFactoryDep
from agentarea_common.config import get_settings
from agentarea_common.events.broker import EventBroker
from agentarea_common.events.event_stream_service import EventStreamService
from agentarea_common.infrastructure.database import get_db_session
from agentarea_common.infrastructure.secret_manager import BaseSecretManager
from agentarea_llm.application.model_instance_service import ModelInstanceService
from agentarea_llm.application.provider_service import ProviderService
from agentarea_llm.infrastructure.model_instance_repository import ModelInstanceRepository
from agentarea_llm.infrastructure.model_spec_repository import ModelSpecRepository
from agentarea_llm.infrastructure.provider_config_repository import ProviderConfigRepository
from agentarea_llm.infrastructure.provider_spec_repository import ProviderSpecRepository
from agentarea_mcp.application.service import MCPServerInstanceService, MCPServerService
from agentarea_secrets.secret_manager_factory import get_real_secret_manager
from agentarea_tasks.infrastructure.repository import TaskRepository
from agentarea_tasks.task_service import TaskService
from agentarea_tasks.temporal_task_manager import TemporalTaskManager
from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

# Initialize module logger early to avoid NameError in import-time branches
logger = logging.getLogger(__name__)

# Trigger system imports (conditional to avoid import errors)
try:
    from agentarea_triggers.infrastructure.repository import (
        TriggerExecutionRepository,
        TriggerRepository,
    )
    from agentarea_triggers.temporal_schedule_manager import TemporalScheduleManager
    from agentarea_triggers.trigger_service import TriggerService
    from agentarea_triggers.webhook_manager import DefaultWebhookManager, WebhookExecutionCallback

    TRIGGERS_AVAILABLE = True
except ImportError as e:
    logger.warning(f"Triggers module not available: {e}")
    TRIGGERS_AVAILABLE = False

    # Create dummy classes to prevent import errors
    class TriggerService:
        pass

    class TriggerRepository:
        pass

    class TriggerExecutionRepository:
        pass

    class DefaultWebhookManager:
        pass

    class WebhookExecutionCallback:
        pass

    class TemporalScheduleManager:
        pass


async def get_event_broker() -> EventBroker:
    """Get EventBroker instance - uses connection manager singleton."""
    from agentarea_common.infrastructure.connection_manager import get_connection_manager

    connection_manager = get_connection_manager()
    return await connection_manager.get_event_broker()


# Common database dependency
DatabaseSessionDep = Annotated[AsyncSession, Depends(get_db_session)]

# Common event broker dependency
EventBrokerDep = Annotated[EventBroker, Depends(get_event_broker)]


# Secret Manager dependencies
async def get_secret_manager(
    db_session: DatabaseSessionDep,
    user_context: UserContextDep,
) -> BaseSecretManager:
    """Get SecretManager instance based on configuration."""
    from agentarea_common.config.secrets import get_secret_manager_settings

    get_secret_manager_settings()
    return get_real_secret_manager(
        session=db_session,
        user_context=user_context,
    )


BaseSecretManagerDep = Annotated[BaseSecretManager, Depends(get_secret_manager)]


# Agent Service dependencies
async def get_agent_service(
    repository_factory: RepositoryFactoryDep,
    event_broker: EventBrokerDep,
) -> AgentService:
    """Get an AgentService instance for the current request."""
    return AgentService(repository_factory, event_broker)


# LLM Service dependencies
async def get_provider_service(
    db_session: DatabaseSessionDep,
    user_context: UserContextDep,
    secret_manager: BaseSecretManagerDep,
    event_broker: EventBrokerDep,
) -> ProviderService:
    """Get a ProviderService instance for the current request."""
    provider_config_repository = ProviderConfigRepository(db_session, user_context)
    provider_spec_repository = ProviderSpecRepository(db_session, user_context)
    model_spec_repository = ModelSpecRepository(db_session, user_context)
    model_instance_repository = ModelInstanceRepository(db_session, user_context)
    return ProviderService(
        provider_spec_repo=provider_spec_repository,
        provider_config_repo=provider_config_repository,
        model_spec_repo=model_spec_repository,
        model_instance_repo=model_instance_repository,
        event_broker=event_broker,
        secret_manager=secret_manager,
    )


async def get_model_instance_service(
    db_session: DatabaseSessionDep,
    user_context: UserContextDep,
    secret_manager: BaseSecretManagerDep,
    event_broker: EventBrokerDep,
) -> ModelInstanceService:
    """Get a ModelInstanceService instance for the current request."""
    model_instance_repository = ModelInstanceRepository(db_session, user_context)
    return ModelInstanceService(
        repository=model_instance_repository,
        event_broker=event_broker,
        secret_manager=secret_manager,
    )


# Task Service dependencies


async def get_task_service(
    repository_factory: RepositoryFactoryDep,
    event_broker: EventBrokerDep,
) -> TaskService:
    from agentarea_tasks.task_service import TaskService
    from agentarea_tasks.temporal_task_manager import TemporalTaskManager

    # Create task repository using factory for task manager
    task_repository = repository_factory.create_repository(TaskRepository)
    task_manager = TemporalTaskManager(task_repository)
    workflow_service = await get_temporal_workflow_service()
    return TaskService(
        repository_factory=repository_factory,
        event_broker=event_broker,
        task_manager=task_manager,
        workflow_service=workflow_service,
    )


async def get_task_manager(
    repository_factory: RepositoryFactoryDep,
):
    task_repository = repository_factory.create_repository(TaskRepository)
    return TemporalTaskManager(task_repository)


async def get_event_stream_service(
    event_broker: EventBrokerDep,
) -> EventStreamService:
    """Get an EventStreamService instance for the current request."""
    from agentarea_common.events.redis_event_broker import RedisEventBroker

    if isinstance(event_broker, RedisEventBroker):
        return EventStreamService(event_broker.redis_broker)
    else:
        raise ValueError(
            f"Expected RedisEventBroker but got {type(event_broker).__name__}. "
            "EventStreamService requires a Redis-backed broker."
        )


async def get_temporal_workflow_service() -> TemporalWorkflowService:
    """Get a TemporalWorkflowService instance for the current request.

    This service uses Temporal workflows for non-blocking task execution.
    """
    execution_service = await get_execution_service()
    return TemporalWorkflowService(execution_service)


async def get_execution_service() -> ExecutionServiceInterface:
    """Get execution service instance - uses connection manager singleton."""
    from agentarea_common.infrastructure.connection_manager import get_connection_manager

    connection_manager = get_connection_manager()
    return await connection_manager.get_execution_service()


# MCP Service dependencies
async def get_mcp_server_service(
    repository_factory: RepositoryFactoryDep,
    event_broker: EventBrokerDep,
) -> MCPServerService:
    """Get a MCPServerService instance for the current request."""
    return MCPServerService(repository_factory, event_broker)


async def get_mcp_server_instance_service(
    repository_factory: RepositoryFactoryDep,
    secret_manager: BaseSecretManagerDep,
    event_broker: EventBrokerDep,
) -> MCPServerInstanceService:
    """Get a MCPServerInstanceService instance for the current request."""
    return MCPServerInstanceService(
        repository_factory=repository_factory,
        event_broker=event_broker,
        secret_manager=secret_manager,
    )


# Common service type hints for easier use
AgentServiceDep = Annotated[AgentService, Depends(get_agent_service)]
ProviderServiceDep = Annotated[ProviderService, Depends(get_provider_service)]
ModelInstanceServiceDep = Annotated[ModelInstanceService, Depends(get_model_instance_service)]
TaskServiceDep = Annotated[TaskService, Depends(get_task_service)]
TaskManagerDep = Annotated[TemporalTaskManager, Depends(get_task_manager)]
EventStreamServiceDep = Annotated[EventStreamService, Depends(get_event_stream_service)]
TemporalWorkflowServiceDep = Annotated[
    TemporalWorkflowService, Depends(get_temporal_workflow_service)
]
MCPServerServiceDep = Annotated[MCPServerService, Depends(get_mcp_server_service)]
MCPServerInstanceServiceDep = Annotated[
    MCPServerInstanceService, Depends(get_mcp_server_instance_service)
]


# Additional backward compatibility functions
async def get_model_spec_repository(
    db_session: DatabaseSessionDep, user_context: UserContextDep
) -> ModelSpecRepository:
    """Get a ModelSpecRepository instance for the current request."""
    return ModelSpecRepository(db_session, user_context)


# Trigger Service dependencies


class TriggerServiceWebhookCallback(WebhookExecutionCallback):
    """Webhook execution callback that delegates to TriggerService."""

    def __init__(self, trigger_service):
        self.trigger_service = trigger_service

    async def execute_webhook_trigger(self, webhook_id: str, request_data: dict):
        """Execute webhook trigger via TriggerService."""
        if not TRIGGERS_AVAILABLE:
            # Return a mock failed execution
            from datetime import datetime
            from uuid import uuid4

            return {
                "id": str(uuid4()),
                "trigger_id": str(uuid4()),
                "executed_at": datetime.utcnow().isoformat(),
                "status": "failed",
                "execution_time_ms": 0,
                "error_message": "Triggers service not available",
            }

        # Find trigger by webhook_id
        trigger = await self.trigger_service.get_trigger_by_webhook_id(webhook_id)
        if not trigger:
            from datetime import datetime
            from uuid import uuid4

            from agentarea_triggers.domain.enums import ExecutionStatus
            from agentarea_triggers.domain.models import TriggerExecution

            # Return failed execution for unknown webhook
            return TriggerExecution(
                id=uuid4(),
                trigger_id=uuid4(),  # Dummy ID
                executed_at=datetime.utcnow(),
                status=ExecutionStatus.FAILED,
                execution_time_ms=0,
                error_message=f"Webhook {webhook_id} not found",
            )

        # Execute the trigger
        return await self.trigger_service.execute_trigger(trigger.id, request_data)


async def get_trigger_service(
    repository_factory: RepositoryFactoryDep,
    event_broker: EventBrokerDep,
    secret_manager: BaseSecretManagerDep,
):
    """Get a TriggerService instance for the current request."""
    if not TRIGGERS_AVAILABLE:
        raise HTTPException(status_code=503, detail="Triggers service not available")

    settings = get_settings()

    # Get task service using repository factory
    task_service = await get_task_service(repository_factory, event_broker)

    # Create LLM condition evaluator if enabled
    llm_condition_evaluator = None
    if settings.triggers.ENABLE_LLM_CONDITIONS:
        try:
            from agentarea_triggers.llm_condition_evaluator import LLMConditionEvaluator

            model_instance_service = await get_model_instance_service(
                repository_factory.session,
                repository_factory.user_context,
                secret_manager,
                event_broker,
            )
            llm_condition_evaluator = LLMConditionEvaluator(
                model_instance_service=model_instance_service, secret_manager=secret_manager
            )
        except Exception as e:
            logger.warning(f"LLM condition evaluator not available: {e}")

    # Create temporal schedule manager
    temporal_schedule_manager = None
    try:
        temporal_schedule_manager = TemporalScheduleManager(
            namespace=settings.triggers.TEMPORAL_SCHEDULE_NAMESPACE,
            task_queue=settings.triggers.TEMPORAL_SCHEDULE_TASK_QUEUE,
        )
    except Exception as e:
        logger.warning(f"Temporal schedule manager not available: {e}")

    return TriggerService(
        repository_factory=repository_factory,
        event_broker=event_broker,
        task_service=task_service,
        llm_condition_evaluator=llm_condition_evaluator,
        temporal_schedule_manager=temporal_schedule_manager,
    )


async def get_webhook_manager(
    event_broker: EventBrokerDep,
    repository_factory: RepositoryFactoryDep,
    secret_manager: BaseSecretManagerDep,
):
    """Get a WebhookManager instance for the current request."""
    if not TRIGGERS_AVAILABLE:
        # Return a mock webhook manager
        class MockWebhookManager:
            async def handle_webhook_request(self, *args, **kwargs):
                return {
                    "status_code": 503,
                    "body": {"status": "error", "message": "Triggers service not available"},
                }

            async def is_healthy(self):
                return False

        return MockWebhookManager()

    settings = get_settings()
    trigger_service = await get_trigger_service(repository_factory, event_broker, secret_manager)
    execution_callback = TriggerServiceWebhookCallback(trigger_service)

    return DefaultWebhookManager(
        execution_callback=execution_callback,
        event_broker=event_broker,
        base_url=settings.triggers.WEBHOOK_BASE_URL,
    )


async def get_trigger_health_check(
    repository_factory: RepositoryFactoryDep,
    event_broker: EventBrokerDep,
    secret_manager: BaseSecretManagerDep,
):
    """Get a TriggerSystemHealthCheck instance for the current request."""
    if not TRIGGERS_AVAILABLE:
        # Return a mock health checker
        class MockHealthCheck:
            async def check_all_components(self):
                return {
                    "overall_status": "unavailable",
                    "timestamp": datetime.utcnow().isoformat(),
                    "components": {
                        "triggers": {
                            "status": "unavailable",
                            "message": "Triggers service not available",
                        }
                    },
                }

        return MockHealthCheck()

    from agentarea_triggers.health_checks import TriggerSystemHealthCheck

    trigger_repository = repository_factory.create_repository(TriggerRepository)
    trigger_execution_repository = repository_factory.create_repository(TriggerExecutionRepository)
    webhook_manager = await get_webhook_manager(event_broker, repository_factory, secret_manager)

    # Get temporal schedule manager
    temporal_schedule_manager = None
    try:
        settings = get_settings()
        temporal_schedule_manager = TemporalScheduleManager(
            namespace=settings.triggers.TEMPORAL_SCHEDULE_NAMESPACE,
            task_queue=settings.triggers.TEMPORAL_SCHEDULE_TASK_QUEUE,
        )
    except Exception as e:
        logger.warning(f"Temporal schedule manager not available for health check: {e}")

    return TriggerSystemHealthCheck(
        trigger_repository=trigger_repository,
        trigger_execution_repository=trigger_execution_repository,
        temporal_schedule_manager=temporal_schedule_manager,
        webhook_manager=webhook_manager,
    )


# Type hints for trigger services (conditional)
if TRIGGERS_AVAILABLE:
    TriggerServiceDep = Annotated[TriggerService, Depends(get_trigger_service)]
    WebhookManagerDep = Annotated[DefaultWebhookManager, Depends(get_webhook_manager)]

    from agentarea_triggers.health_checks import TriggerSystemHealthCheck

    TriggerHealthCheckDep = Annotated[TriggerSystemHealthCheck, Depends(get_trigger_health_check)]
else:
    # Create dummy type hints when triggers are not available
    TriggerServiceDep = None
    WebhookManagerDep = None
    TriggerHealthCheckDep = None


# Cleanup is now handled by the ConnectionManager singleton
