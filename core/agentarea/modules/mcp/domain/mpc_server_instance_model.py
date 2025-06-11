from sqlalchemy import Column, String, DateTime, Text, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
from typing import Optional, Dict, Any, List
import uuid

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
        description: Optional[str] = None,
        server_spec_id: Optional[str] = None,
        json_spec: Optional[Dict[str, Any]] = None,
        status: str = "pending"
    ):
        self.name = name
        self.description = description
        self.server_spec_id = server_spec_id
        self.json_spec = json_spec or {}
        self.status = status

    def get_configured_env_vars(self) -> List[str]:
        """
        Get list of environment variable names configured for this instance.
        
        Returns:
            List of environment variable names (actual values stored in secret manager)
        """
        return self.json_spec.get("env_vars", [])
