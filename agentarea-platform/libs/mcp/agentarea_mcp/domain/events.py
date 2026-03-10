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


# ---------------------------------------------------------------------------
# MCP Auth Config events
# ---------------------------------------------------------------------------


class MCPAuthConfigCreated(DomainEvent):
    def __init__(self, config_id: UUID, auth_type: str, name: str):
        super().__init__()
        self.config_id = config_id
        self.auth_type = auth_type
        self.name = name


class MCPAuthConfigUpdated(DomainEvent):
    def __init__(self, config_id: UUID, name: str):
        super().__init__()
        self.config_id = config_id
        self.name = name


class MCPAuthConfigDeleted(DomainEvent):
    def __init__(self, config_id: UUID):
        super().__init__()
        self.config_id = config_id


# ---------------------------------------------------------------------------
# Compound MCP events
# ---------------------------------------------------------------------------


class CompoundMCPCreated(DomainEvent):
    def __init__(self, compound_id: UUID, name: str, routing_mode: str):
        super().__init__()
        self.compound_id = compound_id
        self.name = name
        self.routing_mode = routing_mode


class CompoundMCPUpdated(DomainEvent):
    def __init__(self, compound_id: UUID, name: str):
        super().__init__()
        self.compound_id = compound_id
        self.name = name


class CompoundMCPDeleted(DomainEvent):
    def __init__(self, compound_id: UUID):
        super().__init__()
        self.compound_id = compound_id


# ---------------------------------------------------------------------------
# Compound Skill events
# ---------------------------------------------------------------------------


class CompoundSkillCreated(DomainEvent):
    def __init__(self, compound_id: UUID, name: str, version: str):
        super().__init__()
        self.compound_id = compound_id
        self.name = name
        self.version = version


class CompoundSkillUpdated(DomainEvent):
    def __init__(self, compound_id: UUID, name: str):
        super().__init__()
        self.compound_id = compound_id
        self.name = name


class CompoundSkillDeleted(DomainEvent):
    def __init__(self, compound_id: UUID):
        super().__init__()
        self.compound_id = compound_id


# ---------------------------------------------------------------------------
# MCP OAuth Link events
# ---------------------------------------------------------------------------


class MCPOAuthLinkCreated(DomainEvent):
    def __init__(self, link_id: UUID, mcp_instance_id: UUID, access_control: str):
        super().__init__()
        self.link_id = link_id
        self.mcp_instance_id = mcp_instance_id
        self.access_control = access_control


class MCPOAuthLinkRevoked(DomainEvent):
    def __init__(self, link_id: UUID, mcp_instance_id: UUID):
        super().__init__()
        self.link_id = link_id
        self.mcp_instance_id = mcp_instance_id
