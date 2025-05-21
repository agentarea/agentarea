from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ....common.base.models import BaseModel


class LLMProvider(BaseModel):
    __tablename__ = "llm_providers"

    id: Mapped[str] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    description: Mapped[str] = mapped_column(String, nullable=True)
    is_builtin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)

    models = relationship("LLMModel", back_populates="provider")

    def __repr__(self):
        return f"<LLMProvider {self.name} ({self.id})>"

class LLMModel(BaseModel):
    __tablename__ = "llm_models"

    id: Mapped[str] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(String, nullable=False)
    provider_id: Mapped[str] = mapped_column(PgUUID(as_uuid=True), ForeignKey("llm_providers.id"), nullable=False)
    model_type: Mapped[str] = mapped_column(String, nullable=False)
    endpoint_url: Mapped[str] = mapped_column(String, nullable=False)
    context_window: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)

    provider = relationship("LLMProvider", back_populates="models")
    instances = relationship("LLMModelInstance", back_populates="model")
    
    def __repr__(self):
        return f"<LLMModel {self.name} ({self.id})>"

class LLMModelInstance(BaseModel):
    __tablename__ = "llm_model_instances"

    id: Mapped[str] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    model_id: Mapped[str] = mapped_column(PgUUID(as_uuid=True), ForeignKey("llm_models.id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(String, nullable=False)
    api_key: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)
    
    model = relationship("LLMModel", back_populates="instances")