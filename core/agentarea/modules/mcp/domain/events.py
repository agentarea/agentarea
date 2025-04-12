from uuid import UUID

from agentarea.common.events.base import DomainEvent


class MCPServerCreated(DomainEvent):
    def __init__(self, server_id: UUID, name: str, version: str):
        super().__init__()
        self.server_id = server_id
        self.name = name
        self.version = version


class MCPServerUpdated(DomainEvent):
    def __init__(self, server_id: UUID, name: str, version: str):
        super().__init__()
        self.server_id = server_id
        self.name = name
        self.version = version


class MCPServerDeleted(DomainEvent):
    def __init__(self, server_id: UUID):
        super().__init__()
        self.server_id = server_id


class MCPServerDeployed(DomainEvent):
    def __init__(self, server_id: UUID, name: str, version: str):
        super().__init__()
        self.server_id = server_id
        self.name = name
        self.version = version 