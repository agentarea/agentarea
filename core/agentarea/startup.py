"""Application startup configuration for AgentArea.

This module handles initialization of services, dependency injection setup,
and other startup tasks required by the AgentArea platform.
"""

import logging

from fastapi import FastAPI

# Temporarily disabled due to Google ADK import issues
# from agentarea.modules.agents.application.agent_communication_service import (
#     AgentCommunicationService,
# )

logger = logging.getLogger(__name__)


def register_services():
    """Services are now registered via FastAPI dependency injection.
    
    This function is kept for compatibility but no longer registers
    services with a custom DI container.
    """
    logger.info("Services are registered via FastAPI dependency injection")


async def startup_event(app: FastAPI):
    """Handle application startup events.
    
    This function is called when the FastAPI application starts up.
    It initializes services and registers them with the DI container.
    """
    logger.info("Starting AgentArea application")

    # Register all services
    register_services()

    logger.info("AgentArea application started successfully")


async def shutdown_event(app: FastAPI):
    """Handle application shutdown events.
    
    This function is called when the FastAPI application shuts down.
    It performs cleanup and resource release.
    """
    logger.info("Shutting down AgentArea application")


def setup_app(app: FastAPI):
    """Configure the FastAPI application with startup and shutdown events.
    
    Args:
        app: The FastAPI application instance to configure
    """
    app.add_event_handler("startup", lambda: startup_event(app))
    app.add_event_handler("shutdown", lambda: shutdown_event(app))
