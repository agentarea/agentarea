from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps.database import get_db_session
from ...common.events.broker import EventBroker, get_event_broker
from ...modules.agents.application.service import AgentService
from ...modules.agents.infrastructure.repository import AgentRepository


async def get_agent_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    event_broker: Annotated[EventBroker, Depends(get_event_broker)]
) -> AgentService:
    repository = AgentRepository(session)
    return AgentService(repository, event_broker) 