from typing import Any
from uuid import UUID

from agentarea_common.events.base_events import DomainEvent


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
    def __init__(
        self, instance_id: str, server_spec_id: str | None, name: str, json_spec: dict[str, Any]
    ):
        super().__init__(
            instance_id=instance_id, server_spec_id=server_spec_id, name=name, json_spec=json_spec
        )
        self.instance_id = instance_id
        self.server_spec_id = server_spec_id
        self.name = name
        self.json_spec = json_spec


class MCPServerInstanceUpdated(DomainEvent):
    def __init__(self, instance_id: UUID, server_spec_id: str | None, name: str, status: str):
        super().__init__()
        self.instance_id = instance_id
        self.server_spec_id = server_spec_id
        self.name = name
        self.status = status


class MCPServerInstanceDeleted(DomainEvent):
    def __init__(self, instance_id: UUID):
        super().__init__(instance_id=str(instance_id))
        self.instance_id = instance_id


class MCPServerInstanceStarted(DomainEvent):
    def __init__(self, instance_id: UUID, server_spec_id: str | None, name: str):
        super().__init__()
        self.instance_id = instance_id
        self.server_spec_id = server_spec_id
        self.name = name


class MCPServerInstanceStopped(DomainEvent):
    def __init__(self, instance_id: UUID, server_spec_id: str | None, name: str):
        super().__init__()
        self.instance_id = instance_id
        self.server_spec_id = server_spec_id
        self.name = name
