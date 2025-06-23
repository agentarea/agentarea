from typing import Any
from uuid import UUID

from agentarea_common.events.base_events import DomainEvent


class AgentCreated(DomainEvent):
    """Event emitted when a new agent is created."""

    def __init__(
        self,
        agent_id: UUID,
        name: str,
        description: str,
        model_id: str,
        tools_config: dict[str, Any] | None = None,
        events_config: dict[str, Any] | None = None,
        planning: bool | None = None,
    ) -> None:
        super().__init__()
        self.agent_id = agent_id
        self.name = name
        self.description = description
        self.model_id = model_id
        self.tools_config = tools_config
        self.events_config = events_config
        self.planning = planning


class AgentUpdated(DomainEvent):
    """Event emitted when an agent is updated."""

    def __init__(
        self,
        agent_id: UUID,
        name: str,
        description: str | None = None,
        model_id: str | None = None,
        tools_config: dict[str, Any] | None = None,
        events_config: dict[str, Any] | None = None,
        planning: bool | None = None,
    ) -> None:
        super().__init__()
        self.agent_id = agent_id
        self.name = name
        self.description = description
        self.model_id = model_id
        self.tools_config = tools_config
        self.events_config = events_config
        self.planning = planning


class AgentDeleted(DomainEvent):
    """Event emitted when an agent is deleted."""

    def __init__(self, agent_id: UUID) -> None:
        super().__init__()
        self.agent_id = agent_id
