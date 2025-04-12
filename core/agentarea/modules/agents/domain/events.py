from typing import List
from uuid import UUID
from ....common.events.base_events import DomainEvent

class AgentCreated(DomainEvent):
    """Event emitted when a new agent is created"""
    agent_id: UUID
    name: str
    capabilities: List[str]

class AgentUpdated(DomainEvent):
    """Event emitted when an agent is updated"""
    agent_id: UUID
    name: str
    capabilities: List[str]

class AgentDeleted(DomainEvent):
    """Event emitted when an agent is deleted"""
    agent_id: UUID 