"""Simple and effective connection manager for AgentArea.

This provides a clean singleton pattern that avoids circular imports
while still providing connection reuse and proper cleanup.
"""

import asyncio
import logging
from inspect import isawaitable
from threading import Lock
from typing import Any, Optional, cast

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Thread-safe singleton connection manager that reuses expensive connections."""

    _instance: Optional["ConnectionManager"] = None
    _lock = Lock()

    def __new__(cls) -> "ConnectionManager":
        """Return the thread-safe singleton instance."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._event_broker_singleton = None
        self._execution_service_singleton = None
        from agentarea_common.config.app import get_app_settings

        self._environment = get_app_settings().ENVIRONMENT.lower()
        self._initialized = True
        logger.info("ConnectionManager singleton initialized")

    @property
    def is_production(self) -> bool:
        """Check if running in production mode."""
        return self._environment == "production"

    async def get_event_broker(self):
        """Get event broker instance with connection reuse."""
        if self._event_broker_singleton is None:
            try:
                from agentarea_common.config import get_settings
                from agentarea_common.events.factory import create_event_broker

                settings = get_settings()
                self._event_broker_singleton = create_event_broker(settings.broker)
                logger.info(
                    f"Created Redis event broker singleton: "
                    f"{type(self._event_broker_singleton).__name__}"
                )
            except Exception as e:
                logger.error(f"Failed to create Redis event broker: {e}")
                raise e
        else:
            logger.debug("Reusing existing Redis event broker singleton")

        return self._event_broker_singleton

    async def get_execution_service(self):
        """Get execution service instance with connection reuse."""
        if self._execution_service_singleton is None:
            try:
                from agentarea_agents.application.execution_service import ExecutionService
                from agentarea_agents.infrastructure.temporal_orchestrator import (
                    TemporalWorkflowOrchestrator,
                )

                from agentarea_common.config import get_settings

                settings = get_settings()
                orchestrator = TemporalWorkflowOrchestrator(
                    temporal_address=settings.workflow.TEMPORAL_SERVER_URL,
                    task_queue=settings.workflow.TEMPORAL_TASK_QUEUE,
                    max_concurrent_activities=settings.workflow.TEMPORAL_MAX_CONCURRENT_ACTIVITIES,
                    max_concurrent_workflows=settings.workflow.TEMPORAL_MAX_CONCURRENT_WORKFLOWS,
                )
                self._execution_service_singleton = ExecutionService(orchestrator)
                logger.info("Created Temporal execution service singleton")
            except Exception as e:
                logger.error(f"Failed to create Temporal execution service: {e}")
                raise e
        else:
            logger.debug("Reusing existing Temporal execution service singleton")

        return self._execution_service_singleton

    async def get_health_status(self) -> dict:
        """Get health status of all connections."""
        return {
            "environment": self._environment,
            "status": "healthy",
            "services": {
                "event_broker": "initialized"
                if self._event_broker_singleton
                else "not_initialized",
                "execution_service": "initialized"
                if self._execution_service_singleton
                else "not_initialized",
            },
            "connection_reuse": True,
            "singleton_pattern": True,
        }

    async def shutdown(self) -> None:
        """Shutdown all connections with proper cleanup."""
        logger.info("Shutting down connection manager")

        # Clean up event broker
        if self._event_broker_singleton:
            try:
                close = getattr(self._event_broker_singleton, "close", None)
                if close is not None:
                    await close()
                logger.info("Cleaned up event broker singleton")
            except Exception as e:
                logger.warning(f"Error cleaning up event broker: {e}", exc_info=True)
            finally:
                self._event_broker_singleton = None

        # Clean up execution service with more thorough cleanup
        if self._execution_service_singleton:
            try:
                # Close Temporal client if available
                orchestrator = getattr(self._execution_service_singleton, "orchestrator", None)
                if orchestrator is not None and hasattr(orchestrator, "_client"):
                    client = cast(Any, orchestrator)._client
                    if client and hasattr(client, "close"):
                        close_result: Any = client.close()
                        if isawaitable(close_result):
                            await close_result

                # Also try to close the orchestrator itself
                close_orchestrator = getattr(orchestrator, "close", None)
                if callable(close_orchestrator):
                    close_result = close_orchestrator()
                    if isawaitable(close_result):
                        await close_result

                logger.info("Cleaned up execution service singleton")
            except Exception as e:
                logger.warning(f"Error cleaning up execution service: {e}")
            finally:
                self._execution_service_singleton = None

        # Force garbage collection to help clean up any remaining references
        import gc

        gc.collect()

        logger.info("Connection manager shutdown completed")

    @classmethod
    def reset_instance(cls):
        """Reset singleton instance (useful for testing)."""
        with cls._lock:
            cls._instance = None


# Global instance getter
def get_connection_manager() -> ConnectionManager:
    """Get the global connection manager instance."""
    return ConnectionManager()


# Health check endpoint helper
async def get_connection_health() -> dict:
    """Get connection health status for monitoring."""
    manager = get_connection_manager()
    return await manager.get_health_status()


# Cleanup helper for application shutdown
async def cleanup_connections():
    """Cleanup all connections during application shutdown with timeout."""
    manager = get_connection_manager()

    try:
        # Add timeout to prevent hanging during shutdown
        await asyncio.wait_for(manager.shutdown(), timeout=5.0)
    except TimeoutError:
        logger.warning("Connection cleanup timed out after 5 seconds, forcing shutdown")
    except Exception as e:
        logger.error(f"Error during connection cleanup: {e}")
    finally:
        # Always reset the singleton
        ConnectionManager.reset_instance()
