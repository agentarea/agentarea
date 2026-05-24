"""Service interfaces for temporal activity dependency injection.

This module provides the container for injecting basic dependencies
into temporal activities, allowing each activity to create its own
database sessions and services for better retryability.
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agentarea_common.broker import BrokerClient
    from agentarea_common.config import Settings
    from agentarea_common.config.channels import ChannelDeliverySettings
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

    `broker_client` + `channel_delivery_settings` are optional injection
    points used by `publish_workflow_events_activity` to enqueue outbound
    channel deliveries directly to the durable stream — bypassing the
    lossy pub/sub bridge between the workflow and the delivery consumer.
    When unset (tests / callers without channel needs), channel emission
    is skipped.
    """

    settings: "Settings"
    event_broker: "EventBroker"
    secret_manager_factory: "SecretManagerFactory"
    workflow_executor: Any = field(default=None)
    broker_client: "BrokerClient | None" = field(default=None)
    channel_delivery_settings: "ChannelDeliverySettings | None" = field(default=None)


# Legacy alias for backward compatibility during transition
ActivityServicesInterface = ActivityDependencies
