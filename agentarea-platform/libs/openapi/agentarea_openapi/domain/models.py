"""Domain model for OpenAPI connections."""

from typing import Any
from uuid import UUID

from agentarea_common.base.models import BaseModel, WorkspaceScopedMixin
from sqlalchemy import JSON, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column


class OpenAPIConnection(BaseModel, WorkspaceScopedMixin):
    """An OpenAPI-based REST API connection.

    Stores the OpenAPI spec and discovered tools. No lifecycle management
    (no start/stop) — these are always-on external APIs.
    """

    __tablename__ = "openapi_connections"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    spec_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    spec_content: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    auth_config_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("mcp_auth_configs.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Each entry: {"name": "Header-Name", "secret": bool, "value": "plaintext-or-null"}
    # Secret header values are stored in the secret manager, not here.
    custom_headers: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    available_tools: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active")

    def __init__(
        self,
        name: str,
        base_url: str,
        description: str | None = None,
        spec_url: str | None = None,
        spec_content: dict[str, Any] | None = None,
        auth_config_id: UUID | None = None,
        custom_headers: list[dict[str, Any]] | None = None,
        available_tools: list[dict[str, Any]] | None = None,
        status: str = "active",
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.name = name
        self.base_url = base_url
        self.description = description
        self.spec_url = spec_url
        self.spec_content = spec_content
        self.auth_config_id = auth_config_id
        self.custom_headers = custom_headers
        self.available_tools = available_tools or []
        self.status = status
