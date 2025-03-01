import uuid
from sqlalchemy import (
    Column,
    String,
    Enum as SQLAlchemyEnum,
    ForeignKey,
    DateTime,
    JSON,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from enum import Enum
from sqlalchemy.orm import relationship

from ..database import Base


class ModelScope(str, Enum):
    PUBLIC = "PUBLIC"
    PRIVATE = "PRIVATE"


class ModelInstance(Base):
    __tablename__ = "model_instance"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False, index=True)
    description = Column(String)
    version = Column(String, nullable=False)
    provider = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    references = relationship("ModelReference", back_populates="model_instance")


class ModelReference(Base):
    __tablename__ = "model_reference"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    instance_id = Column(
        UUID(as_uuid=True),
        ForeignKey("model_instance.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(String, nullable=False, index=True)
    settings = Column(JSON, nullable=False)
    scope = Column(SQLAlchemyEnum(ModelScope, name="modelscope"), nullable=False)
    status = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    model_instance = relationship("ModelInstance", back_populates="references")
