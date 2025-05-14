from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from agentarea.common.base.models import BaseModel


class MCPServerInstance(BaseModel):
    __tablename__ = "mcp_server_instances"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    server_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("mcp_servers.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    endpoint_url: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="starting")
    config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    def __init__(
        self,
        server_id: UUID,
        name: str,
        endpoint_url: str,
        config: dict = None,
        status: str = "starting",
        id: UUID = None,
        created_at: datetime = None,
        updated_at: datetime = None,
    ):
        self.id = id or uuid4()
        self.server_id = server_id
        self.name = name
        self.endpoint_url = endpoint_url
        self.config = config or {}
        self.status = status
        self.created_at = created_at or datetime.utcnow()
        self.updated_at = updated_at or datetime.utcnow()
