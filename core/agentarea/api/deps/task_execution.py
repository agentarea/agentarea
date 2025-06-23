"""Dependency injection for task execution services."""

from typing import Annotated
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from agentarea.common.infrastructure.database import get_db_session
from agentarea.api.deps.events import get_event_broker
from agentarea.api.deps.services import (
    get_llm_model_instance_service,
    get_mcp_server_instance_service,
)
from agentarea.api.deps.session import get_session_service
from agentarea.common.events.broker import EventBroker
from agentarea.modules.agents.infrastructure.repository import AgentRepository
from agentarea.modules.agents.application.agent_builder_service import AgentBuilderService
from agentarea.modules.agents.application.agent_runner_service import AgentRunnerService
from agentarea.modules.agents.application.agent_communication_service import (
    AgentCommunicationService,
)
from agentarea.modules.agents.application.task_execution_service import TaskExecutionService
from agentarea.modules.llm.application.service import LLMModelInstanceService
from agentarea.modules.mcp.application.service import MCPServerInstanceService
from google.adk.sessions import BaseSessionService


async def get_agent_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AgentRepository:
    """Get agent repository."""
    return AgentRepository(session)


async def get_agent_builder_service(
    agent_repository: Annotated[AgentRepository, Depends(get_agent_repository)],
    event_broker: Annotated[EventBroker, Depends(get_event_broker)],
    llm_model_instance_service: Annotated[
        LLMModelInstanceService, Depends(get_llm_model_instance_service)
    ],
    mcp_server_instance_service: Annotated[
        MCPServerInstanceService, Depends(get_mcp_server_instance_service)
    ],
) -> AgentBuilderService:
    """Get agent builder service with all dependencies."""
    return AgentBuilderService(
        repository=agent_repository,
        event_broker=event_broker,
        llm_model_instance_service=llm_model_instance_service,
        mcp_server_instance_service=mcp_server_instance_service,
    )


class AgentServiceFactory:
    """Factory to create agent services and resolve circular dependencies."""

    def __init__(self):
        self._agent_runner_service = None
        self._agent_communication_service = None

    def create_services(
        self,
        agent_repository: AgentRepository,
        event_broker: EventBroker,
        llm_model_instance_service: LLMModelInstanceService,
        session_service: BaseSessionService,
        agent_builder_service: AgentBuilderService,
    ) -> tuple[AgentRunnerService, AgentCommunicationService]:
        """Create both services and wire them together to resolve circular dependency."""

        if self._agent_runner_service is None or self._agent_communication_service is None:
            # Create AgentRunnerService first without AgentCommunicationService
            self._agent_runner_service = AgentRunnerService(
                repository=agent_repository,
                event_broker=event_broker,
                llm_model_instance_service=llm_model_instance_service,
                session_service=session_service,
                agent_builder_service=agent_builder_service,
                agent_communication_service=None,  # Will be set later
            )

            # Create AgentCommunicationService with AgentRunnerService
            self._agent_communication_service = AgentCommunicationService(
                agent_runner_service=self._agent_runner_service,
                event_broker=event_broker,
                enable_agent_communication=True,
            )

            # Now wire them together
            self._agent_runner_service.agent_communication_service = (
                self._agent_communication_service
            )

        return self._agent_runner_service, self._agent_communication_service


# Global factory instance (singleton pattern)
_agent_service_factory = AgentServiceFactory()


async def get_agent_services(
    agent_repository: Annotated[AgentRepository, Depends(get_agent_repository)],
    event_broker: Annotated[EventBroker, Depends(get_event_broker)],
    llm_model_instance_service: Annotated[
        LLMModelInstanceService, Depends(get_llm_model_instance_service)
    ],
    session_service: Annotated[BaseSessionService, Depends(get_session_service)],
    agent_builder_service: Annotated[AgentBuilderService, Depends(get_agent_builder_service)],
) -> tuple[AgentRunnerService, AgentCommunicationService]:
    """Get both agent runner and communication services with circular dependency resolved."""
    return _agent_service_factory.create_services(
        agent_repository=agent_repository,
        event_broker=event_broker,
        llm_model_instance_service=llm_model_instance_service,
        session_service=session_service,
        agent_builder_service=agent_builder_service,
    )


async def get_agent_runner_service(
    services: Annotated[
        tuple[AgentRunnerService, AgentCommunicationService], Depends(get_agent_services)
    ],
) -> AgentRunnerService:
    """Get agent runner service."""
    return services[0]


async def get_agent_communication_service(
    services: Annotated[
        tuple[AgentRunnerService, AgentCommunicationService], Depends(get_agent_services)
    ],
) -> AgentCommunicationService:
    """Get agent communication service."""
    return services[1]


async def get_task_execution_service(
    agent_repository: Annotated[AgentRepository, Depends(get_agent_repository)],
    event_broker: Annotated[EventBroker, Depends(get_event_broker)],
    llm_model_instance_service: Annotated[
        LLMModelInstanceService, Depends(get_llm_model_instance_service)
    ],
    mcp_server_instance_service: Annotated[
        MCPServerInstanceService, Depends(get_mcp_server_instance_service)
    ],
    session_service: Annotated[BaseSessionService, Depends(get_session_service)],
    agent_communication_service: Annotated[
        AgentCommunicationService, Depends(get_agent_communication_service)
    ],
) -> TaskExecutionService:
    """Get task execution service with all dependencies including session service."""
    return TaskExecutionService(
        agent_repository=agent_repository,
        event_broker=event_broker,
        llm_model_instance_service=llm_model_instance_service,
        mcp_server_instance_service=mcp_server_instance_service,
        session_service=session_service,
        agent_communication_service=agent_communication_service,
    )


# Type aliases for dependency injection
AgentRepositoryDep = Annotated[AgentRepository, Depends(get_agent_repository)]
AgentBuilderServiceDep = Annotated[AgentBuilderService, Depends(get_agent_builder_service)]
AgentRunnerServiceDep = Annotated[AgentRunnerService, Depends(get_agent_runner_service)]
AgentCommunicationServiceDep = Annotated[
    AgentCommunicationService, Depends(get_agent_communication_service)
]
TaskExecutionServiceDep = Annotated[TaskExecutionService, Depends(get_task_execution_service)]
