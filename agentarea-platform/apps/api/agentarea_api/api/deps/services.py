"""Service dependencies for FastAPI endpoints.

This module provides dependency injection functions for services
used across the AgentArea API endpoints.
"""

import logging
from datetime import datetime
from typing import Annotated, Final

from agentarea_agents.application.agent_service import AgentService
from agentarea_agents.application.skill_service import SkillService
from agentarea_agents.application.temporal_workflow_service import TemporalWorkflowService
from agentarea_agents.application.workspace_export_service import WorkspaceExportService
from agentarea_agents.domain.interfaces import ExecutionServiceInterface
from agentarea_common.audit.service import AuditService
from agentarea_common.auth import UserContextDep
from agentarea_common.base import ReadRepositoryFactoryDep, RepositoryFactoryDep
from agentarea_common.config import get_settings
from agentarea_common.config.database import get_db_session
from agentarea_common.events.broker import EventBroker
from agentarea_common.infrastructure.secret_manager import BaseSecretManager
from agentarea_common.utils.url_safety import OutboundPolicy
from agentarea_llm.application.model_instance_service import ModelInstanceService
from agentarea_llm.application.model_spec_service import ModelSpecService
from agentarea_llm.application.provider_service import ProviderService
from agentarea_llm.infrastructure.model_instance_repository import ModelInstanceRepository
from agentarea_llm.infrastructure.model_spec_repository import ModelSpecRepository
from agentarea_llm.infrastructure.provider_config_repository import ProviderConfigRepository
from agentarea_llm.infrastructure.provider_spec_repository import ProviderSpecRepository
from agentarea_mcp.application.service import MCPServerInstanceService, MCPServerService
from agentarea_openapi.application.service import OpenAPIConnectionService
from agentarea_registry.application.service import RegistryService
from agentarea_registry.infrastructure.repository import (
    RegistryItemRepository,
    RegistryRepository,
)
from agentarea_secrets.catalog_service import SecretCatalogService
from agentarea_secrets.secret_manager_factory import get_real_secret_manager
from agentarea_tasks.domain.interfaces import BaseTaskManager
from agentarea_tasks.infrastructure.repository import TaskRepository
from agentarea_tasks.task_service import TaskService
from agentarea_triggers.infrastructure.repository import (
    TriggerExecutionRepository,
    TriggerRepository,
)
from agentarea_triggers.temporal_schedule_manager import TemporalScheduleManager
from agentarea_triggers.trigger_service import TriggerService
from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

# Initialize module logger early to avoid NameError in import-time branches
logger = logging.getLogger(__name__)

TRIGGERS_AVAILABLE: Final = True


async def get_event_broker() -> EventBroker:
    """Get EventBroker instance - uses connection manager singleton."""
    from agentarea_common.infrastructure.connection_manager import get_connection_manager

    connection_manager = get_connection_manager()
    return await connection_manager.get_event_broker()


# Common database dependency
DatabaseSessionDep = Annotated[AsyncSession, Depends(get_db_session, scope="function")]

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


async def get_secret_catalog_service(
    db_session: DatabaseSessionDep,
    user_context: UserContextDep,
    secret_manager: BaseSecretManagerDep,
) -> SecretCatalogService:
    """Catalog operations on top of whichever secret backend is configured."""
    return SecretCatalogService(
        session=db_session,
        user_context=user_context,
        secret_manager=secret_manager,
    )


SecretCatalogServiceDep = Annotated[SecretCatalogService, Depends(get_secret_catalog_service)]


# Audit Service dependencies
async def get_audit_service(
    db_session: DatabaseSessionDep,
    user_context: UserContextDep,
) -> AuditService:
    """Get an AuditService instance for the current request."""
    return AuditService(db_session, user_context)


AuditServiceDep = Annotated[AuditService, Depends(get_audit_service)]


# Agent Service dependencies
async def get_agent_service(
    repository_factory: RepositoryFactoryDep,
    event_broker: EventBrokerDep,
) -> AgentService:
    """Get an AgentService instance for the current request."""
    from agentarea_common.auth.authorization import AuthorizationService
    from agentarea_common.di.container import resolve

    authz = resolve(AuthorizationService)
    return AgentService(repository_factory, event_broker, authorization_service=authz)


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

    task_manager = await _create_task_manager(repository_factory)
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
    return await _create_task_manager(repository_factory)


async def _create_task_manager(repository_factory: RepositoryFactoryDep):
    """Create task manager based on AGENTAREA_TASK_EXECUTOR setting.

    "temporal" (default): Uses Temporal workflows for durable execution.
    "direct": Runs agent loop in-process. No Temporal/workers needed.
    """
    from agentarea_common.config import get_settings

    settings = get_settings()

    task_repository = repository_factory.create_repository(TaskRepository)

    if settings.app.TASK_EXECUTOR == "direct":
        from agentarea_tasks.direct_task_manager import DirectTaskManager

        logger.info("Using DirectTaskManager (in-process, no Temporal)")
        return DirectTaskManager(task_repository)

    from agentarea_tasks.temporal_task_manager import TemporalTaskManager

    return TemporalTaskManager(task_repository)


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


async def get_registry_service(
    db_session: DatabaseSessionDep,
    user_context: UserContextDep,
) -> RegistryService:
    """Get a RegistryService instance for the current request."""
    from agentarea_agents.infrastructure.skill_repository import SkillRepository
    from agentarea_mcp.infrastructure.repository import MCPServerRepository

    registry_repo = RegistryRepository(db_session, user_context)
    item_repo = RegistryItemRepository(db_session, user_context)
    server_repo = MCPServerRepository(db_session, user_context)
    skill_repo = SkillRepository(db_session, user_context)
    return RegistryService(registry_repo, item_repo, server_repo, skill_repo)


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


async def get_skill_service(
    repository_factory: RepositoryFactoryDep,
    user_context: UserContextDep,
) -> SkillService:
    """Get a SkillService instance for the current request."""
    return SkillService(
        repository_factory=repository_factory,
        user_context=user_context,
    )


async def get_workspace_export_service(
    repository_factory: RepositoryFactoryDep,
    event_broker: EventBrokerDep,
    mcp_instance_service: Annotated[
        "MCPServerInstanceService", Depends(get_mcp_server_instance_service)
    ],
    skill_service: Annotated["SkillService", Depends(get_skill_service)],
) -> WorkspaceExportService:
    """Get a WorkspaceExportService instance for the current request."""
    from agentarea_common.auth.authorization import AuthorizationService
    from agentarea_common.di.container import resolve
    from agentarea_triggers.infrastructure.repository import TriggerRepository

    authz = resolve(AuthorizationService)
    agent_service = AgentService(repository_factory, event_broker, authorization_service=authz)
    return WorkspaceExportService(
        agent_service=agent_service,
        repository_factory=repository_factory,
        mcp_instance_service=mcp_instance_service,
        skill_service=skill_service,
        trigger_repository=repository_factory.create_repository(TriggerRepository),
    )


async def get_openapi_connection_service(
    repository_factory: RepositoryFactoryDep,
    secret_manager: BaseSecretManagerDep,
) -> OpenAPIConnectionService:
    """Get an OpenAPIConnectionService instance for the current request."""
    from agentarea_mcp.application.auth_resolver import (
        build_auth_config_access_checker,
        build_auth_header_resolver,
    )

    return OpenAPIConnectionService(
        repository_factory=repository_factory,
        secret_manager=secret_manager,
        auth_header_resolver=build_auth_header_resolver(repository_factory, secret_manager),
        auth_config_access_checker=build_auth_config_access_checker(
            repository_factory,
            secret_manager,
        ),
        outbound_policy=OutboundPolicy.from_env(),
    )


async def get_read_agent_service(
    repository_factory: ReadRepositoryFactoryDep,
    event_broker: EventBrokerDep,
) -> AgentService:
    """Get a read-only AgentService (uses AUTOCOMMIT session)."""
    from agentarea_common.auth.authorization import AuthorizationService
    from agentarea_common.di.container import resolve

    authz = resolve(AuthorizationService)
    return AgentService(repository_factory, event_broker, authorization_service=authz)


async def get_read_task_service(
    repository_factory: ReadRepositoryFactoryDep,
    event_broker: EventBrokerDep,
) -> TaskService:
    """Get a read-only TaskService (uses AUTOCOMMIT session)."""
    task_manager = await _create_task_manager(repository_factory)
    workflow_service = await get_temporal_workflow_service()
    return TaskService(
        repository_factory=repository_factory,
        event_broker=event_broker,
        task_manager=task_manager,
        workflow_service=workflow_service,
    )


# Common service type hints for easier use
AgentServiceDep = Annotated[AgentService, Depends(get_agent_service)]
SkillServiceDep = Annotated[SkillService, Depends(get_skill_service)]
WorkspaceExportServiceDep = Annotated[WorkspaceExportService, Depends(get_workspace_export_service)]
ProviderServiceDep = Annotated[ProviderService, Depends(get_provider_service)]
ModelInstanceServiceDep = Annotated[ModelInstanceService, Depends(get_model_instance_service)]
TaskServiceDep = Annotated[TaskService, Depends(get_task_service)]
TaskManagerDep = Annotated[BaseTaskManager, Depends(get_task_manager)]
ReadAgentServiceDep = Annotated[AgentService, Depends(get_read_agent_service)]
ReadTaskServiceDep = Annotated[TaskService, Depends(get_read_task_service)]
TemporalWorkflowServiceDep = Annotated[
    TemporalWorkflowService, Depends(get_temporal_workflow_service)
]
MCPServerServiceDep = Annotated[MCPServerService, Depends(get_mcp_server_service)]
MCPServerInstanceServiceDep = Annotated[
    MCPServerInstanceService, Depends(get_mcp_server_instance_service)
]
OpenAPIConnectionServiceDep = Annotated[
    OpenAPIConnectionService, Depends(get_openapi_connection_service)
]


# Additional backward compatibility functions
async def get_model_spec_repository(
    db_session: DatabaseSessionDep, user_context: UserContextDep
) -> ModelSpecRepository:
    """Get a ModelSpecRepository instance for the current request."""
    return ModelSpecRepository(db_session, user_context)


async def get_model_spec_service(
    model_spec_repo: ModelSpecRepository = Depends(get_model_spec_repository),
) -> ModelSpecService:
    return ModelSpecService(model_spec_repo)


# Trigger Service dependencies


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
    if settings.triggers.LLM_ENABLED:
        try:
            from agentarea_triggers.llm_condition_evaluator import LLMConditionEvaluator

            model_instance_service = await get_model_instance_service(
                repository_factory.session,
                repository_factory.user_context,
                secret_manager,
                event_broker,
            )
            from agentarea_common.config.secrets import get_secret_manager_settings
            from agentarea_llm.application.model_service import build_model_service
            from agentarea_secrets.secret_manager_factory import SecretManagerFactory

            llm_condition_evaluator = LLMConditionEvaluator(
                model_instance_service=model_instance_service,
                secret_manager=secret_manager,
                model_service=build_model_service(
                    session=repository_factory.session,
                    user_context=repository_factory.user_context,
                    secret_manager_factory=SecretManagerFactory(get_secret_manager_settings()),
                ),
            )
        except Exception as e:
            logger.warning(f"LLM condition evaluator not available: {e}", exc_info=True)

    # Create temporal schedule manager
    temporal_schedule_manager = None
    try:
        temporal_schedule_manager = TemporalScheduleManager(
            task_queue=settings.triggers.QUEUE,
        )
    except Exception as e:
        logger.warning(f"Temporal schedule manager not available: {e}", exc_info=True)

    return TriggerService(
        repository_factory=repository_factory,
        event_broker=event_broker,
        task_service=task_service,
        llm_condition_evaluator=llm_condition_evaluator,
        temporal_schedule_manager=temporal_schedule_manager,
        secret_manager=secret_manager,
    )


async def get_public_webhook_manager(
    db_session: DatabaseSessionDep,
    event_broker: EventBrokerDep,
):
    """Get a WebhookManager instance for PUBLIC webhook endpoints (no auth required).

    This creates a webhook manager without requiring UserContext, since external
    services (Telegram, Slack, GitHub, etc.) cannot provide authentication headers.
    The webhook_id in the URL is the sole identifier for routing to the correct trigger.
    """
    if not TRIGGERS_AVAILABLE:

        class MockWebhookManager:
            async def handle_webhook_request(self, *args, **kwargs):
                return {
                    "status_code": 503,
                    "body": {"status": "error", "message": "Triggers service not available"},
                }

            async def is_healthy(self):
                return False

        return MockWebhookManager()

    from agentarea_api.api.v1._webhook_intake import WebhookSourceIntake
    from agentarea_common.config.database import get_database
    from agentarea_common.di.container import resolve
    from agentarea_streams.domain.ports import StreamWaker

    return WebhookSourceIntake(
        lookup_session=db_session,
        session_scope=get_database().session,
        secret_reader_for=lambda session, context: get_real_secret_manager(
            session=session, user_context=context
        ),
        waker=resolve(StreamWaker),
        event_broker=event_broker,
        settings=get_settings(),
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
    webhook_manager = await get_public_webhook_manager(repository_factory.session, event_broker)

    # Get temporal schedule manager
    temporal_schedule_manager = None
    try:
        settings = get_settings()
        temporal_schedule_manager = TemporalScheduleManager(
            task_queue=settings.triggers.QUEUE,
        )
    except Exception as e:
        logger.warning(
            f"Temporal schedule manager not available for health check: {e}", exc_info=True
        )

    return TriggerSystemHealthCheck(
        trigger_repository=trigger_repository,
        trigger_execution_repository=trigger_execution_repository,
        temporal_schedule_manager=temporal_schedule_manager,
        webhook_manager=webhook_manager,
    )


# Type hints for trigger services (conditional)
if TRIGGERS_AVAILABLE:
    TriggerServiceDep = Annotated[TriggerService, Depends(get_trigger_service)]

    from agentarea_triggers.health_checks import TriggerSystemHealthCheck

    TriggerHealthCheckDep = Annotated[TriggerSystemHealthCheck, Depends(get_trigger_health_check)]
else:
    # Create dummy type hints when triggers are not available
    TriggerServiceDep = None
    TriggerHealthCheckDep = None


# Cleanup is now handled by the ConnectionManager singleton
