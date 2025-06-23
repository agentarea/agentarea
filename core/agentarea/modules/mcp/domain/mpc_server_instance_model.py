import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Column, DateTime, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()


class MCPServerInstance(Base):
    __tablename__ = "mcp_server_instances"

    id = Column(UUID(as_uuid=True), primary_key=True, index=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    server_spec_id = Column(String(255), nullable=True)  # Nullable for external providers
    json_spec = Column(JSON, nullable=False)  # Unified configuration storage
    status = Column(String(50), default="pending")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __init__(
        self,
        name: str,
        description: str | None = None,
        server_spec_id: str | None = None,
        json_spec: dict[str, Any] | None = None,
        status: str = "pending",
    ):
        self.name = name
        self.description = description
        self.server_spec_id = server_spec_id
        self.json_spec = json_spec or {}
        self.status = status

    def get_configured_env_vars(self) -> list[str]:
        """Get list of environment variable names configured for this instance.

        Returns:
            List of environment variable names from the environment section of json_spec
        """
        environment = self.json_spec.get("environment", {})
        if isinstance(environment, dict):
            return [str(key) for key in environment.keys()]
        return []
