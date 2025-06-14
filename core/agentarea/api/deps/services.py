"""
Service dependencies for FastAPI endpoints.

This module provides dependency injection functions for services
used across the AgentArea API endpoints.
"""

import logging
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from agentarea.common.di.container import get_instance
from agentarea.common.events.broker import EventBroker
from agentarea.common.infrastructure.database import get_db_session
from agentarea.modules.tasks.infrastructure.repository import SQLAlchemyTaskRepository
from agentarea.modules.tasks.task_service import TaskService

logger = logging.getLogger(__name__)


async def get_task_repository(db: Annotated[AsyncSession, Depends(get_db_session)]):
    """
    Get a TaskRepository instance for the current request.
    
    Uses a new database session for each request to ensure transaction isolation.
    """
    return SQLAlchemyTaskRepository(db)


async def get_task_service(
    event_broker: Annotated[EventBroker, Depends(get_instance(EventBroker))],
    task_repository: Annotated[SQLAlchemyTaskRepository, Depends(get_task_repository)]
):
    """
    Get a TaskService instance for the current request.
    
    Combines the global EventBroker singleton with a request-scoped TaskRepository.
    """
    return TaskService(event_broker=event_broker, task_repository=task_repository)
