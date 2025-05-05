from typing import List
from uuid import UUID
from ....common.events.base_events import DomainEvent


class AgentCreated(DomainEvent):
    """Event emitted when a new agent is created"""

    agent_id: UUID
    name: str
    description: str
    model_id: str
    tools_config: dict | None = None
    events_config: dict | None = None
    planning: str | None = None


class AgentUpdated(DomainEvent):
    """Event emitted when an agent is updated"""

    agent_id: UUID
    name: str
    description: str | None = None
    model_id: str | None = None
    tools_config: dict | None = None
    events_config: dict | None = None
    planning: str | None = None


class AgentDeleted(DomainEvent):
    """Event emitted when an agent is deleted"""

    agent_id: UUID
