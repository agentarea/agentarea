"""Dependency Injection Container for Agent Services.

Properly injects all dependencies from configuration without defaults.
Follows dependency inversion principle strictly.
"""

import logging

from agentarea_common.config import WorkflowSettings, get_settings

from ..application.execution_service import ExecutionService, WorkflowOrchestratorInterface
from .workflow_factory import WorkflowFactory

logger = logging.getLogger(__name__)


class DIContainer:
    """Dependency injection container for agent services."""

    def __init__(self, workflow_settings: WorkflowSettings):
        """Initialize container with injected configuration."""
        if not workflow_settings:
            raise ValueError("WorkflowSettings must be provided - no defaults allowed")

        self._workflow_settings = workflow_settings
        self._workflow_factory: WorkflowFactory | None = None
        self._execution_service: ExecutionService | None = None

    def get_workflow_factory(self) -> WorkflowFactory:
        """Get workflow factory with injected configuration."""
        if self._workflow_factory is None:
            # Create config adapter from settings
            config = _WorkflowConfigAdapter(self._workflow_settings)
            self._workflow_factory = WorkflowFactory(config)
            logger.info("Created WorkflowFactory with injected config")

        return self._workflow_factory

    def get_execution_service(self) -> ExecutionService:
        """Get execution service with fully injected dependencies."""
        if self._execution_service is None:
            factory = self.get_workflow_factory()
            orchestrator = factory.create_temporal_orchestrator()
            self._execution_service = ExecutionService(orchestrator)
            logger.info("Created ExecutionService with injected dependencies")

        return self._execution_service

    def get_temporal_orchestrator(self) -> WorkflowOrchestratorInterface:
        """Get Temporal orchestrator with injected configuration."""
        factory = self.get_workflow_factory()
        return factory.create_temporal_orchestrator()


class _WorkflowConfigAdapter:
    """Adapter to convert WorkflowSettings to WorkflowConfig protocol."""

    def __init__(self, settings: WorkflowSettings):
        # Map settings to protocol attributes
        self.temporal_address: str = settings.TEMPORAL_SERVER_URL
        self.task_queue: str = settings.TEMPORAL_TASK_QUEUE
        self.max_concurrent_activities: int = settings.TEMPORAL_MAX_CONCURRENT_ACTIVITIES
        self.max_concurrent_workflows: int = settings.TEMPORAL_MAX_CONCURRENT_WORKFLOWS


# Global DI container - initialized with proper config injection
_di_container: DIContainer | None = None


def initialize_di_container(workflow_settings: WorkflowSettings | None = None) -> None:
    """Initialize the global DI container with configuration."""
    global _di_container

    if workflow_settings is None:
        # Get from global config - still proper injection, just from global source
        settings = get_settings()
        workflow_settings = settings.workflow

    _di_container = DIContainer(workflow_settings)
    logger.info("Initialized DI container with workflow settings")


def get_di_container() -> DIContainer:
    """Get the global DI container."""
    global _di_container

    if _di_container is None:
        # Auto-initialize with global config if not explicitly initialized
        initialize_di_container()

    if _di_container is None:
        raise RuntimeError("Failed to initialize DI container")

    return _di_container


def get_execution_service() -> ExecutionService:
    """Factory function that uses proper DI."""
    container = get_di_container()
    return container.get_execution_service()


def get_workflow_factory() -> WorkflowFactory:
    """Factory function that uses proper DI."""
    container = get_di_container()
    return container.get_workflow_factory()
