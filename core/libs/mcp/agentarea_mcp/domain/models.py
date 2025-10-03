from typing import Any

from agentarea_common.base.models import AuditMixin, BaseModel, WorkspaceScopedMixin
from sqlalchemy import JSON, Boolean, String
from sqlalchemy.orm import Mapped, declarative_base, mapped_column

Base = declarative_base()


class MCPServer(BaseModel, WorkspaceScopedMixin, AuditMixin):
    """MCP Server model with workspace awareness and audit trail."""

    __tablename__ = "mcp_servers"

    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(String, nullable=False)
    docker_image_url: Mapped[str] = mapped_column(String, nullable=False)
    version: Mapped[str] = mapped_column(String, nullable=False)
    tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String, nullable=False, default="draft")
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Environment variable schema - defines what env vars this server needs
    env_schema: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    # Custom command to override container CMD - useful for switching between stdio and HTTP modes
    cmd: Mapped[list[str] | None] = mapped_column(JSON, nullable=True, default=None)

    def __init__(
        self,
        name: str,
        description: str,
        docker_image_url: str,
        version: str,
        tags: list[str] | None = None,
        status: str = "draft",
        is_public: bool = False,
        env_schema: list[dict[str, Any]] | None = None,
        cmd: list[str] | None = None,
        # Note: user_id and workspace_id are now handled by BaseModel
        **kwargs,
    ):
        super().__init__(**kwargs)  # Let BaseModel handle id, timestamps, user_id, workspace_id
        self.name = name
        self.description = description
        self.docker_image_url = docker_image_url
        self.version = version
        self.tags = tags or []
        self.status = status
        self.is_public = is_public
        self.env_schema = env_schema or []
        self.cmd = cmd
