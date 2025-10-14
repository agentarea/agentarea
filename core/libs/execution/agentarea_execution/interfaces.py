"""Service interfaces for temporal activity dependency injection.

This module provides the container for injecting basic dependencies
into temporal activities, allowing each activity to create its own
database sessions and services for better retryability.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentarea_common.config import Settings
    from agentarea_common.events.broker import EventBroker
    from agentarea_secrets.secret_manager_factory import SecretManagerFactory


@dataclass
class ActivityDependencies:
    """Container for basic dependencies needed by temporal activities.

    This class provides only the essential dependencies that activities
    need to create their own database sessions and services. Each activity
    will create its own session using get_database().async_session_factory()
    for better retryability and resource isolation.

    The secret_manager_factory is used by activities to create workspace-scoped
    secret manager instances with the proper user context at activity execution time.
    """

    settings: "Settings"
    event_broker: "EventBroker"
    secret_manager_factory: "SecretManagerFactory"


# Legacy alias for backward compatibility during transition
ActivityServicesInterface = ActivityDependencies
