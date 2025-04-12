from datetime import datetime
from uuid import uuid4

from sqlalchemy import JSON, Column, DateTime, String
from sqlalchemy.dialects.postgresql import UUID as PgUUID

from ....common.base.models import BaseModel


class Agent(BaseModel):
    __tablename__ = "agents"

    id = Column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(String, nullable=False)
    capabilities = Column(JSON, nullable=False, default=list)
    status = Column(String, nullable=False, default="active")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f"<Agent {self.name} ({self.id})>" 