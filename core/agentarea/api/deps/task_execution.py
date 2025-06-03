"""Dependency injection for task execution services."""
from typing import Annotated
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from agentarea.common.infrastructure.database import get_db_session
from agentarea.api.deps.events import get_event_broker
from agentarea.api.deps.services import get_llm_model_instance_service, get_mcp_server_instance_service
from agentarea.api.deps.session import get_session_service
from agentarea.common.events.broker import EventBroker
from agentarea.modules.agents.infrastructure.repository import AgentRepository
from agentarea.modules.agents.application.agent_builder_service import AgentBuilderService
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
    llm_model_instance_service: Annotated[LLMModelInstanceService, Depends(get_llm_model_instance_service)],
    mcp_server_instance_service: Annotated[MCPServerInstanceService, Depends(get_mcp_server_instance_service)],
) -> AgentBuilderService:
    """Get agent builder service with all dependencies."""
    return AgentBuilderService(
        repository=agent_repository,
        event_broker=event_broker,
        llm_model_instance_service=llm_model_instance_service,
        mcp_server_instance_service=mcp_server_instance_service
    )


async def get_task_execution_service(
    agent_repository: Annotated[AgentRepository, Depends(get_agent_repository)],
    event_broker: Annotated[EventBroker, Depends(get_event_broker)],
    llm_model_instance_service: Annotated[LLMModelInstanceService, Depends(get_llm_model_instance_service)],
    mcp_server_instance_service: Annotated[MCPServerInstanceService, Depends(get_mcp_server_instance_service)],
    session_service: Annotated[BaseSessionService, Depends(get_session_service)],
) -> TaskExecutionService:
    """Get task execution service with all dependencies including session service."""
    return TaskExecutionService(
        agent_repository=agent_repository,
        event_broker=event_broker,
        llm_model_instance_service=llm_model_instance_service,
        mcp_server_instance_service=mcp_server_instance_service,
        session_service=session_service
    )


# Type aliases for dependency injection
AgentRepositoryDep = Annotated[AgentRepository, Depends(get_agent_repository)]
AgentBuilderServiceDep = Annotated[AgentBuilderService, Depends(get_agent_builder_service)]
TaskExecutionServiceDep = Annotated[TaskExecutionService, Depends(get_task_execution_service)] 