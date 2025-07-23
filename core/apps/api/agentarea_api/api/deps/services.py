"""Service dependencies for FastAPI endpoints.

This module provides dependency injection functions for services
used across the AgentArea API endpoints.
"""

import logging
from typing import Annotated

from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from agentarea_tasks.task_service import TaskService
from agentarea_tasks.temporal_task_manager import TemporalTaskManager

from agentarea_agents.application.agent_service import AgentService
from agentarea_agents.application.execution_service import ExecutionService
from agentarea_agents.application.temporal_workflow_service import TemporalWorkflowService
from agentarea_agents.domain.interfaces import ExecutionServiceInterface
from agentarea_agents.infrastructure.repository import AgentRepository

from agentarea_common.config import get_settings
from agentarea_common.events.broker import EventBroker
from agentarea_common.events.router import get_event_router
from agentarea_common.infrastructure.database import get_db_session
from agentarea_common.infrastructure.secret_manager import BaseSecretManager
from agentarea_secrets import get_real_secret_manager

from agentarea_llm.application.model_instance_service import ModelInstanceService
from agentarea_llm.application.provider_service import ProviderService
from agentarea_llm.infrastructure.model_instance_repository import ModelInstanceRepository
from agentarea_llm.infrastructure.model_spec_repository import ModelSpecRepository
from agentarea_llm.infrastructure.provider_config_repository import ProviderConfigRepository
from agentarea_llm.infrastructure.provider_spec_repository import ProviderSpecRepository

from agentarea_mcp.application.service import MCPServerInstanceService, MCPServerService
from agentarea_mcp.infrastructure.repository import MCPServerInstanceRepository, MCPServerRepository

from agentarea_tasks.infrastructure.repository import TaskRepository

# Trigger system imports (conditional to avoid import errors)
try:
    from agentarea_triggers.trigger_service import TriggerService
    from agentarea_triggers.infrastructure.repository import TriggerRepository, TriggerExecutionRepository
    from agentarea_triggers.webhook_manager import DefaultWebhookManager, WebhookExecutionCallback
    from agentarea_triggers.temporal_schedule_manager import TemporalScheduleManager
    TRIGGERS_AVAILABLE = True
except ImportError as e:
    logger.warning(f"Triggers module not available: {e}")
    TRIGGERS_AVAILABLE = False
    # Create dummy classes to prevent import errors
    class TriggerService: pass
    class TriggerRepository: pass
    class TriggerExecutionRepository: pass
    class DefaultWebhookManager: pass
    class WebhookExecutionCallback: pass
    class TemporalScheduleManager: pass

logger = logging.getLogger(__name__)


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


# Common database dependency
DatabaseSessionDep = Annotated[AsyncSession, Depends(get_db_session)]

# Common event broker dependency
EventBrokerDep = Annotated[EventBroker, Depends(get_event_broker)]

# Secret Manager dependencies
BaseSecretManagerDep = Annotated[BaseSecretManager, Depends(get_real_secret_manager)]


# Agent Service dependencies
async def get_agent_service(
    db_session: DatabaseSessionDep,
    event_broker: EventBrokerDep,
) -> AgentService:
    """Get an AgentService instance for the current request."""
    repository = AgentRepository(db_session)
    return AgentService(repository, event_broker)


# LLM Service dependencies
async def get_provider_service(
    db_session: DatabaseSessionDep,
    secret_manager: BaseSecretManagerDep,
    event_broker: EventBrokerDep,
) -> ProviderService:
    """Get a ProviderService instance for the current request."""
    provider_config_repository = ProviderConfigRepository(db_session)
    provider_spec_repository = ProviderSpecRepository(db_session)
    model_spec_repository = ModelSpecRepository(db_session)
    model_instance_repository = ModelInstanceRepository(db_session)
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
    secret_manager: BaseSecretManagerDep,
    event_broker: EventBrokerDep,
) -> ModelInstanceService:
    """Get a ModelInstanceService instance for the current request."""
    model_instance_repository = ModelInstanceRepository(db_session)
    return ModelInstanceService(
        repository=model_instance_repository,
        event_broker=event_broker,
        secret_manager=secret_manager,
    )


# Task Service dependencies
async def get_task_repository(db_session: DatabaseSessionDep) -> TaskRepository:
    """Get a TaskRepository instance for the current request."""
    return TaskRepository(db_session)


async def get_agent_repository(db_session: DatabaseSessionDep) -> AgentRepository:
    """Get an AgentRepository instance for the current request."""
    return AgentRepository(db_session)


async def get_task_service(
    db_session: DatabaseSessionDep,
    event_broker: EventBrokerDep,
) -> TaskService:
    from agentarea_tasks.task_service import TaskService
    from agentarea_tasks.temporal_task_manager import TemporalTaskManager

    task_repository = await get_task_repository(db_session)
    agent_repository = await get_agent_repository(db_session)
    task_manager = TemporalTaskManager(task_repository)
    workflow_service = await get_temporal_workflow_service()
    return TaskService(
        task_repository=task_repository,
        event_broker=event_broker,
        task_manager=task_manager,
        agent_repository=agent_repository,
        workflow_service=workflow_service,
    )


async def get_task_manager(db_session: DatabaseSessionDep):
    task_repository = await get_task_repository(db_session)
    return TemporalTaskManager(task_repository)


async def get_temporal_workflow_service() -> TemporalWorkflowService:
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
    event_broker: EventBrokerDep,
) -> MCPServerService:
    """Get a MCPServerService instance for the current request."""
    repository = MCPServerRepository(db_session)
    return MCPServerService(repository, event_broker)


async def get_mcp_server_instance_service(
    db_session: DatabaseSessionDep,
    secret_manager: BaseSecretManagerDep,
    event_broker: EventBrokerDep,
) -> MCPServerInstanceService:
    """Get a MCPServerInstanceService instance for the current request."""
    repository = MCPServerInstanceRepository(db_session)
    mcp_server_repository = MCPServerRepository(db_session)
    return MCPServerInstanceService(
        repository=repository,
        event_broker=event_broker,
        mcp_server_repository=mcp_server_repository,
        secret_manager=secret_manager,
    )


# Common service type hints for easier use
AgentServiceDep = Annotated[AgentService, Depends(get_agent_service)]
AgentRepositoryDep = Annotated[AgentRepository, Depends(get_agent_repository)]
ProviderServiceDep = Annotated[ProviderService, Depends(get_provider_service)]
ModelInstanceServiceDep = Annotated[ModelInstanceService, Depends(get_model_instance_service)]
TaskRepositoryDep = Annotated[TaskRepository, Depends(get_task_repository)]
TaskServiceDep = Annotated[TaskService, Depends(get_task_service)]
TaskManagerDep = Annotated[TemporalTaskManager, Depends(get_task_manager)]
TemporalWorkflowServiceDep = Annotated[
    TemporalWorkflowService, Depends(get_temporal_workflow_service)
]
MCPServerServiceDep = Annotated[MCPServerService, Depends(get_mcp_server_service)]
MCPServerInstanceServiceDep = Annotated[
    MCPServerInstanceService, Depends(get_mcp_server_instance_service)
]


# Additional backward compatibility functions
async def get_model_spec_repository(db_session: DatabaseSessionDep) -> ModelSpecRepository:
    """Get a ModelSpecRepository instance for the current request."""
    return ModelSpecRepository(db_session)


async def get_secret_manager() -> BaseSecretManager:
    """Get SecretManager instance - real Infisical implementation."""
    return get_real_secret_manager()


# Trigger Service dependencies
async def get_trigger_repository(db_session: DatabaseSessionDep):
    """Get a TriggerRepository instance for the current request."""
    if not TRIGGERS_AVAILABLE:
        raise HTTPException(status_code=503, detail="Triggers service not available")
    return TriggerRepository(db_session)


async def get_trigger_execution_repository(db_session: DatabaseSessionDep):
    """Get a TriggerExecutionRepository instance for the current request."""
    if not TRIGGERS_AVAILABLE:
        raise HTTPException(status_code=503, detail="Triggers service not available")
    return TriggerExecutionRepository(db_session)


class TriggerServiceWebhookCallback(WebhookExecutionCallback):
    """Webhook execution callback that delegates to TriggerService."""
    
    def __init__(self, trigger_service):
        self.trigger_service = trigger_service
    
    async def execute_webhook_trigger(self, webhook_id: str, request_data: dict):
        """Execute webhook trigger via TriggerService."""
        if not TRIGGERS_AVAILABLE:
            # Return a mock failed execution
            from uuid import uuid4
            from datetime import datetime
            return {
                "id": str(uuid4()),
                "trigger_id": str(uuid4()),
                "executed_at": datetime.utcnow().isoformat(),
                "status": "failed",
                "execution_time_ms": 0,
                "error_message": "Triggers service not available"
            }
        
        # Find trigger by webhook_id
        trigger = await self.trigger_service.get_trigger_by_webhook_id(webhook_id)
        if not trigger:
            from agentarea_triggers.domain.models import TriggerExecution
            from agentarea_triggers.domain.enums import ExecutionStatus
            from uuid import uuid4
            from datetime import datetime
            
            # Return failed execution for unknown webhook
            return TriggerExecution(
                id=uuid4(),
                trigger_id=uuid4(),  # Dummy ID
                executed_at=datetime.utcnow(),
                status=ExecutionStatus.FAILED,
                execution_time_ms=0,
                error_message=f"Webhook {webhook_id} not found"
            )
        
        # Execute the trigger
        return await self.trigger_service.execute_trigger(trigger.id, request_data)


async def get_trigger_service(
    db_session: DatabaseSessionDep,
    event_broker: EventBrokerDep,
    secret_manager: BaseSecretManagerDep,
):
    """Get a TriggerService instance for the current request."""
    if not TRIGGERS_AVAILABLE:
        raise HTTPException(status_code=503, detail="Triggers service not available")
    
    trigger_repository = await get_trigger_repository(db_session)
    trigger_execution_repository = await get_trigger_execution_repository(db_session)
    agent_repository = await get_agent_repository(db_session)
    task_service = await get_task_service(db_session, event_broker)
    
    # Create LLM condition evaluator
    llm_condition_evaluator = None
    try:
        from agentarea_triggers.llm_condition_evaluator import LLMConditionEvaluator
        model_instance_service = await get_model_instance_service(db_session, secret_manager, event_broker)
        llm_condition_evaluator = LLMConditionEvaluator(
            model_instance_service=model_instance_service,
            secret_manager=secret_manager
        )
    except Exception as e:
        logger.warning(f"LLM condition evaluator not available: {e}")
    
    # Optional: Add temporal schedule manager if available
    temporal_schedule_manager = None
    try:
        temporal_schedule_manager = TemporalScheduleManager()
    except Exception as e:
        logger.warning(f"Temporal schedule manager not available: {e}")
    
    return TriggerService(
        trigger_repository=trigger_repository,
        trigger_execution_repository=trigger_execution_repository,
        event_broker=event_broker,
        agent_repository=agent_repository,
        task_service=task_service,
        llm_condition_evaluator=llm_condition_evaluator,
        temporal_schedule_manager=temporal_schedule_manager
    )


async def get_webhook_manager(
    event_broker: EventBrokerDep,
    db_session: DatabaseSessionDep,
    secret_manager: BaseSecretManagerDep,
):
    """Get a WebhookManager instance for the current request."""
    if not TRIGGERS_AVAILABLE:
        # Return a mock webhook manager
        class MockWebhookManager:
            async def handle_webhook_request(self, *args, **kwargs):
                return {
                    "status_code": 503,
                    "body": {
                        "status": "error",
                        "message": "Triggers service not available"
                    }
                }
            
            async def is_healthy(self):
                return False
        
        return MockWebhookManager()
    
    trigger_service = await get_trigger_service(db_session, event_broker, secret_manager)
    execution_callback = TriggerServiceWebhookCallback(trigger_service)
    
    return DefaultWebhookManager(
        execution_callback=execution_callback,
        event_broker=event_broker,
        base_url="/v1/webhooks"
    )


# Type hints for trigger services (conditional)
if TRIGGERS_AVAILABLE:
    TriggerRepositoryDep = Annotated[TriggerRepository, Depends(get_trigger_repository)]
    TriggerExecutionRepositoryDep = Annotated[TriggerExecutionRepository, Depends(get_trigger_execution_repository)]
    TriggerServiceDep = Annotated[TriggerService, Depends(get_trigger_service)]
    WebhookManagerDep = Annotated[DefaultWebhookManager, Depends(get_webhook_manager)]
