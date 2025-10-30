"""Workflow factory using dependency injection pattern."""

import logging
from typing import Protocol

from ..application.execution_service import WorkflowOrchestratorInterface
from .temporal_orchestrator import TemporalWorkflowOrchestrator

logger = logging.getLogger(__name__)


class WorkflowConfig(Protocol):
    """Protocol for workflow configuration."""

    temporal_address: str
    task_queue: str
    max_concurrent_activities: int
    max_concurrent_workflows: int


class WorkflowFactory:
    """Factory for creating workflow orchestrators."""

    def __init__(self, config: WorkflowConfig):
        """Initialize factory with required configuration - no defaults allowed."""
        if not config:
            raise ValueError("WorkflowConfig must be provided - no defaults allowed")

        self._config = config
        self._orchestrator_cache: dict[str, WorkflowOrchestratorInterface] = {}

    def create_temporal_orchestrator(self) -> WorkflowOrchestratorInterface:
        """Create Temporal workflow orchestrator using injected config."""
        # Use configuration from injected config - no defaults
        address = self._config.temporal_address

        # Use cached orchestrator if available
        cache_key = f"temporal_{address}"
        if cache_key in self._orchestrator_cache:
            return self._orchestrator_cache[cache_key]

        # Create new orchestrator with injected config
        orchestrator = TemporalWorkflowOrchestrator(
            temporal_address=address,
            task_queue=self._config.task_queue,
            max_concurrent_activities=self._config.max_concurrent_activities,
            max_concurrent_workflows=self._config.max_concurrent_workflows,
        )
        self._orchestrator_cache[cache_key] = orchestrator

        logger.info(f"Created Temporal orchestrator with injected config: {address}")
        return orchestrator

    # def create_default_orchestrator(self) -> WorkflowOrchestratorInterface:
    #     """Create default workflow orchestrator (Temporal)."""
    #     return self.create_temporal_orchestrator()

    def clear_cache(self) -> None:
        """Clear orchestrator cache."""
        self._orchestrator_cache.clear()
        logger.info("Workflow orchestrator cache cleared")


# Global factory functions removed - use di_container.py for proper DI
