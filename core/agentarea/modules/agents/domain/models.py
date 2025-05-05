from datetime import datetime
from uuid import uuid4

from sqlalchemy import JSON, Column, DateTime, String
from sqlalchemy.dialects.postgresql import UUID as PgUUID

from ....common.base.models import BaseModel


class Agent(BaseModel):
    __tablename__ = "agents"

    id = Column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(String, nullable=False)
    status = Column(String, nullable=False, default="active")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    description = Column(String, nullable=True)
    model_id = Column(String, nullable=True)
    tools_config = Column(JSON, nullable=True)
    events_config = Column(JSON, nullable=True)
    planning = Column(String, nullable=True)