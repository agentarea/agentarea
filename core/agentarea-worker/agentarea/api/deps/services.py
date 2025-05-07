from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from agentarea.common.events.broker import EventBroker, get_event_broker
from agentarea.common.infrastructure.database import get_db_session
from core.agentarea.modules.agents.application.agent_service import AgentService
from agentarea.modules.agents.infrastructure.repository import AgentRepository
from agentarea.modules.llm.application.service import LLMModelService, LLMModelInstanceService
from core.agentarea.modules.llm.infrastructure.llm_model_repository import LLMModelRepository
from agentarea.modules.mcp.application.service import MCPServerService, MCPServerInstanceService
from agentarea.modules.mcp.infrastructure.repository import MCPServerRepository, MCPServerInstanceRepository
from core.agentarea.modules.llm.infrastructure.llm_model_instance_repository import LLMModelInstanceRepository


async def get_agent_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    event_broker: Annotated[EventBroker, Depends(get_event_broker)],
) -> AgentService:
    repository = AgentRepository(session)
    return AgentService(repository, event_broker)


async def get_mcp_server_service(
    session: AsyncSession = Depends(get_db_session),
    event_broker: EventBroker = Depends(get_event_broker),
) -> MCPServerService:
    return MCPServerService(MCPServerRepository(session), event_broker)


async def get_mcp_server_instance_service(
    session: AsyncSession = Depends(get_db_session),
    event_broker: EventBroker = Depends(get_event_broker),
    mcp_server_service: MCPServerService = Depends(get_mcp_server_service),
) -> MCPServerInstanceService:
    mcp_server_repository = MCPServerRepository(session)
    return MCPServerInstanceService(
        MCPServerInstanceRepository(session), 
        event_broker,
        mcp_server_repository
    )


async def get_llm_model_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    event_broker: Annotated[EventBroker, Depends(get_event_broker)]
) -> LLMModelService:
    repository = LLMModelRepository(session)
    return LLMModelService(repository, event_broker)


async def get_llm_model_instance_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    event_broker: Annotated[EventBroker, Depends(get_event_broker)]
) -> LLMModelInstanceService:
    repository = LLMModelInstanceRepository(session)
    return LLMModelInstanceService(repository, event_broker)
