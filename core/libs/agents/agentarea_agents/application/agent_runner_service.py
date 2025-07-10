"""Simplified Agent Runner Service - Facade for the new focused services."""

import logging
from collections.abc import AsyncGenerator
from typing import Any
from uuid import UUID

from agentarea_common.events.broker import EventBroker
from google.adk.sessions import BaseSessionService

from agentarea_agents.infrastructure.repository import AgentRepository

from .agent_builder_service import AgentBuilderService
from .agent_execution_service import AgentExecutionService
from .agent_factory_service import AgentFactoryService

logger = logging.getLogger(__name__)

# Optional import for TemporalLlmAgent
try:
    from agentarea_execution.interfaces import ActivityServicesInterface
    TEMPORAL_AVAILABLE = True
    logger.info("TemporalFlow integration available")
except ImportError:
    TEMPORAL_AVAILABLE = False
    ActivityServicesInterface = None
    logger.debug("TemporalFlow integration not available")


class AgentRunnerService:
    """Simplified facade service that orchestrates agent execution using focused services."""
    
    def __init__(
        self,
        repository: AgentRepository,
        event_broker: EventBroker,
        session_service: BaseSessionService,
        agent_builder_service: AgentBuilderService,
        agent_communication_service: Any | None = None,
        activity_services: Any | None = None,
        enable_temporal_execution: bool = False,
    ):
        self.repository = repository
        self.event_broker = event_broker
        self.session_service = session_service
        self.agent_builder_service = agent_builder_service
        self.agent_communication_service = agent_communication_service
        
        # Create focused services
        self.agent_factory_service = AgentFactoryService(
            activity_services=activity_services,
            enable_temporal_execution=enable_temporal_execution,
        )
        
        self.agent_execution_service = AgentExecutionService(
            event_broker=event_broker,
            session_service=session_service,
            agent_builder_service=agent_builder_service,
            agent_factory_service=self.agent_factory_service,
            agent_communication_service=agent_communication_service,
        )



    async def run_agent_task(
        self,
        agent_id: UUID,
        task_id: str,
        user_id: str,
        query: str,
        task_parameters: dict[str, Any] | None = None,
        enable_agent_communication: bool | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Run an agent to execute a specific task.

        Simplified facade method that delegates to AgentExecutionService.

        Args:
            agent_id: UUID of the agent to run
            task_id: Task identifier
            user_id: User running the task
            query: Query/instruction for the task
            task_parameters: Additional task parameters
            enable_agent_communication: Override flag to enable/disable A2A communication for this run

        Yields:
            Task execution events
        """
        # Delegate to the focused execution service
        async for event in self.agent_execution_service.execute_agent_task(
            agent_id=agent_id,
            task_id=task_id,
            user_id=user_id,
            query=query,
            task_parameters=task_parameters,
            enable_agent_communication=enable_agent_communication,
        ):
            yield event


