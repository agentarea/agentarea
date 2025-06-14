"""
Application startup configuration for AgentArea.

This module handles initialization of services, dependency injection setup,
and other startup tasks required by the AgentArea platform.
"""

import logging
from typing import Optional

from fastapi import FastAPI

from agentarea.common.di.container import register_singleton, get_instance
from agentarea.common.events.broker import EventBroker
from agentarea.modules.tasks.in_memory_task_manager import InMemoryTaskManager
from agentarea.modules.tasks.task_manager import BaseTaskManager
from agentarea.modules.agents.application.agent_communication_service import (
    AgentCommunicationService,
)

logger = logging.getLogger(__name__)


def register_services():
    """
    Register all services with the dependency injection container.
    
    This function is called during application startup to ensure all
    required services are available for dependency injection.
    """
    logger.info("Registering services with DI container")
    
    # Register the task manager
    task_manager = InMemoryTaskManager()
    register_singleton(BaseTaskManager, task_manager)
    logger.info("Registered InMemoryTaskManager as BaseTaskManager")

    # Retrieve already-configured EventBroker (registered during lifespan setup)
    try:
        event_broker = get_instance(EventBroker)
    except Exception:  # pragma: no cover – fail fast if broker missing
        event_broker = None
        logger.warning(
            "EventBroker instance not found in DI container while "
            "initialising AgentCommunicationService"
        )

    # Register AgentCommunicationService if dependencies are available
    if event_broker is not None:
        agent_comm_service = AgentCommunicationService(
            task_manager=task_manager,
            event_broker=event_broker,
        )
        register_singleton(AgentCommunicationService, agent_comm_service)
        logger.info("Registered AgentCommunicationService with DI container")


async def startup_event(app: FastAPI):
    """
    Handle application startup events.
    
    This function is called when the FastAPI application starts up.
    It initializes services and registers them with the DI container.
    """
    logger.info("Starting AgentArea application")
    
    # Register all services
    register_services()
    
    logger.info("AgentArea application started successfully")


async def shutdown_event(app: FastAPI):
    """
    Handle application shutdown events.
    
    This function is called when the FastAPI application shuts down.
    It performs cleanup and resource release.
    """
    logger.info("Shutting down AgentArea application")


def setup_app(app: FastAPI):
    """
    Configure the FastAPI application with startup and shutdown events.
    
    Args:
        app: The FastAPI application instance to configure
    """
    app.add_event_handler("startup", lambda: startup_event(app))
    app.add_event_handler("shutdown", lambda: shutdown_event(app))
