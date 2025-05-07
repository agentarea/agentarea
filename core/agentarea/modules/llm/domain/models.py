from datetime import datetime
from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import relationship

from ....common.base.models import BaseModel


class LLMModel(BaseModel):
    __tablename__ = "llm_models"

    id = Column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(String, nullable=False)
    description = Column(String, nullable=False)
    provider = Column(String, nullable=False)
    model_type = Column(String, nullable=False)
    endpoint_url = Column(String, nullable=False)
    context_window = Column(String, nullable=False)
    status = Column(String, nullable=False, default="active")
    is_public = Column(JSON, nullable=False, default=False)
    updated_at = Column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)
    created_at = Column(DateTime, nullable=False, default=datetime.now)

    instances = relationship("LLMModelInstance", back_populates="model")
    
    def __repr__(self):
        return f"<LLMModel {self.name} ({self.id})>"

class LLMModelInstance(BaseModel):
    __tablename__ = "llm_model_instances"

    id = Column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    model_id = Column(PgUUID(as_uuid=True), ForeignKey("llm_models.id"), nullable=False)
    name = Column(String, nullable=False)
    description = Column(String, nullable=False)
    api_key = Column(String, nullable=False)
    status = Column(String, nullable=False, default="active")
    is_public = Column(JSON, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    model = relationship("LLMModel", back_populates="instances")