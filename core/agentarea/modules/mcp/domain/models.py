from datetime import datetime
from uuid import UUID, uuid4
from typing import Any, Dict, List, Optional

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
    tags: Mapped[List[str]] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String, nullable=False, default="draft")
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Environment variable schema - defines what env vars this server needs
    env_schema: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    # Custom command to override container CMD - useful for switching between stdio and HTTP modes
    cmd: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True, default=None)

    def __init__(
        self,
        name: str,
        description: str,
        docker_image_url: str,
        version: str,
        tags: Optional[List[str]] = None,
        status: str = "draft",
        is_public: bool = False,
        env_schema: Optional[List[Dict[str, Any]]] = None,
        cmd: Optional[List[str]] = None,
        id: Optional[UUID] = None,
        updated_at: Optional[datetime] = None,
    ):
        self.id = id or uuid4()
        self.name = name
        self.description = description
        self.docker_image_url = docker_image_url
        self.version = version
        self.tags = tags or []
        self.status = status
        self.is_public = is_public
        self.env_schema = env_schema or []
        self.cmd = cmd
        self.updated_at = updated_at or datetime.now()
