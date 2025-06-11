from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from agentarea.common.infrastructure.database import get_db_session
from agentarea.common.infrastructure.secret_manager import BaseSecretManager
from agentarea.config import SecretManagerSettings, get_settings
from agentarea.modules.agents.application.agent_service import AgentService
from agentarea.modules.agents.infrastructure.repository import AgentRepository
from agentarea.modules.llm.application.llm_model_service import LLMModelService
from agentarea.modules.llm.application.service import (
    LLMModelInstanceService,
)
from agentarea.modules.llm.infrastructure.llm_model_instance_repository import (
    LLMModelInstanceRepository,
)
from agentarea.modules.llm.infrastructure.llm_model_repository import LLMModelRepository
from agentarea.modules.mcp.application.service import (
    MCPServerInstanceService,
    MCPServerService,
)
from agentarea.modules.mcp.infrastructure.repository import (
    MCPServerInstanceRepository,
    MCPServerRepository,
)
# Domain events import removed - not needed in dependency injection
from agentarea.modules.secrets.db_secret_manager import DBSecretManager
from .events import EventBrokerDep


async def get_secret_manager(
    secret_manager_settings: SecretManagerSettings = Depends(get_settings),
) -> BaseSecretManager:
    # infisical_client = InfisicalSDKClient(
    #     host=secret_manager_settings.SECRET_MANAGER_ENDPOINT,
    #     token=secret_manager_settings.SECRET_MANAGER_ACCESS_KEY,
    # )

    db_secret_manager = DBSecretManager()
    return db_secret_manager


async def get_agent_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    event_broker: EventBrokerDep,
) -> AgentService:
    repository = AgentRepository(session)
    return AgentService(repository, event_broker)


async def get_mcp_server_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    event_broker: EventBrokerDep,
) -> MCPServerService:
    return MCPServerService(MCPServerRepository(session), event_broker)


async def get_mcp_server_instance_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    event_broker: EventBrokerDep,
    secret_manager: Annotated[BaseSecretManager, Depends(get_secret_manager)],
) -> MCPServerInstanceService:
    mcp_server_repository = MCPServerRepository(session)
    return MCPServerInstanceService(
        MCPServerInstanceRepository(session), 
        event_broker, 
        mcp_server_repository,
        secret_manager
    )


async def get_llm_model_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    event_broker: EventBrokerDep,
) -> LLMModelService:
    repository = LLMModelRepository(session)
    return LLMModelService(repository, event_broker)


async def get_llm_model_instance_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    event_broker: EventBrokerDep,
    secret_manager: Annotated[BaseSecretManager, Depends(get_secret_manager)],
) -> LLMModelInstanceService:
    repository = LLMModelInstanceRepository(session)
    return LLMModelInstanceService(repository, event_broker, secret_manager)
