from uuid import UUID

from agentarea.common.events.base_events import DomainEvent


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


class MCPServerInstanceCreated(DomainEvent):
    def __init__(self, instance_id: UUID, server_id: UUID, name: str):
        super().__init__()
        self.instance_id = instance_id
        self.server_id = server_id
        self.name = name


class MCPServerInstanceUpdated(DomainEvent):
    def __init__(self, instance_id: UUID, server_id: UUID, name: str, status: str):
        super().__init__()
        self.instance_id = instance_id
        self.server_id = server_id
        self.name = name
        self.status = status


class MCPServerInstanceDeleted(DomainEvent):
    def __init__(self, instance_id: UUID, server_id: UUID):
        super().__init__()
        self.instance_id = instance_id
        self.server_id = server_id


class MCPServerInstanceStarted(DomainEvent):
    def __init__(self, instance_id: UUID, server_id: UUID, name: str):
        super().__init__()
        self.instance_id = instance_id
        self.server_id = server_id
        self.name = name


class MCPServerInstanceStopped(DomainEvent):
    def __init__(self, instance_id: UUID, server_id: UUID, name: str):
        super().__init__()
        self.instance_id = instance_id
        self.server_id = server_id
        self.name = name 