from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PgUUID

from agentarea.common.base.models import BaseModel


class MCPServer(BaseModel):
    __tablename__ = "mcp_servers"

    id = Column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(String, nullable=False)
    description = Column(String, nullable=False)
    docker_image_url = Column(String, nullable=False)
    version = Column(String, nullable=False)
    tags = Column(JSON, nullable=False, default=list)
    status = Column(String, nullable=False, default="draft")
    is_public = Column(Boolean, nullable=False, default=False)

    def __init__(
        self,
        name: str,
        description: str,
        docker_image_url: str,
        version: str,
        tags: list[str] = None,
        status: str = "draft",
        is_public: bool = False,
        id: UUID = None,
        last_updated: datetime = None,
    ):
        self.id = id or uuid4()
        self.name = name
        self.description = description
        self.docker_image_url = docker_image_url
        self.version = version
        self.tags = tags or []
        self.status = status
        self.is_public = is_public
        self.last_updated = last_updated or datetime.utcnow()


class MCPServerInstance(BaseModel):
    __tablename__ = "mcp_server_instances"

    id = Column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    server_id = Column(
        PgUUID(as_uuid=True), ForeignKey("mcp_servers.id"), nullable=False
    )
    name = Column(String, nullable=False)
    endpoint_url = Column(String, nullable=False)
    status = Column(String, nullable=False, default="starting")
    config = Column(JSON, nullable=False, default=dict)

    def __init__(
        self,
        server_id: UUID,
        name: str,
        endpoint_url: str,
        config: dict = None,
        status: str = "starting",
        id: UUID = None,
        created_at: datetime = None,
        last_updated: datetime = None,
    ):
        self.id = id or uuid4()
        self.server_id = server_id
        self.name = name
        self.endpoint_url = endpoint_url
        self.config = config or {}
        self.status = status
        self.created_at = created_at or datetime.utcnow()
        self.last_updated = last_updated or datetime.utcnow()
