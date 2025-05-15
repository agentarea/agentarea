from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, Boolean, String
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, declarative_base, mapped_column

Base = declarative_base()

from agentarea.common.base.models import BaseModel


class MCPServer(BaseModel):
    __tablename__ = "mcp_servers"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(String, nullable=False)
    docker_image_url: Mapped[str] = mapped_column(String, nullable=False)
    version: Mapped[str] = mapped_column(String, nullable=False)
    tags: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String, nullable=False, default="draft")
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

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

