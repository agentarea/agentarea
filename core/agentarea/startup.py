"""
Startup and shutdown configuration for AgentArea.

This module handles initialization and cleanup of services,
particularly the MCP integration bridge.
"""
import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

from fastapi import FastAPI

from .config import get_settings

logger = logging.getLogger(__name__)


class StartupManager:
    """Manages application startup and shutdown processes."""
    
    def __init__(self):
        self.background_tasks: list[asyncio.Task] = []
        self.settings = get_settings()
    
    async def startup(self) -> None:
        """Initialize services during application startup."""
        logger.info("🚀 Starting AgentArea services...")
        
        try:
            # Start background tasks
            await self._start_background_tasks()
            
            logger.info("✅ All services started successfully")
            
        except Exception as e:
            logger.error(f"❌ Failed to start services: {e}")
            await self.shutdown()
            raise
    
    async def shutdown(self) -> None:
        """Clean up services during application shutdown."""
        logger.info("🛑 Shutting down AgentArea services...")
        
        try:
            # Cancel background tasks
            await self._stop_background_tasks()
            
            logger.info("✅ All services shut down successfully")
            
        except Exception as e:
            logger.error(f"❌ Error during shutdown: {e}")
    
    async def _start_background_tasks(self) -> None:
        """Start background monitoring and synchronization tasks."""
        # Start health monitoring task
        task = asyncio.create_task(
            self._health_monitor(),
            name="health_monitor"
        )
        self.background_tasks.append(task)
        
        logger.info("✅ Background tasks started")
    
    async def _stop_background_tasks(self) -> None:
        """Stop all background tasks."""
        if self.background_tasks:
            logger.info(f"Cancelling {len(self.background_tasks)} background tasks...")
            
            for task in self.background_tasks:
                task.cancel()
            
            await asyncio.gather(*self.background_tasks, return_exceptions=True)
            self.background_tasks.clear()
            
            logger.info("✅ Background tasks stopped")
    
    async def _health_monitor(self) -> None:
        """Monitor service health."""
        while True:
            try:
                # Placeholder for health checks
                logger.debug("Health check passed")
                await asyncio.sleep(30)  # Check every 30 seconds
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in health monitor: {e}")
                await asyncio.sleep(5)


# Global startup manager instance
_startup_manager = StartupManager()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[Any, None]:
    """FastAPI lifespan context manager."""
    # Startup
    await _startup_manager.startup()
    
    try:
        yield
    finally:
        # Shutdown
        await _startup_manager.shutdown()


def get_startup_manager() -> StartupManager:
    """Get the global startup manager instance."""
    return _startup_manager 