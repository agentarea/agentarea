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


class LLMScope(str, Enum):
    PUBLIC = "PUBLIC"
    PRIVATE = "PRIVATE"


class LLMInstance(Base):
    __tablename__ = "llm_instance"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False, index=True)
    description = Column(String)
    version = Column(String, nullable=False)
    provider = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    references = relationship("LLMReference", back_populates="llm_instance")


class LLMReference(Base):
    __tablename__ = "llm_reference"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    instance_id = Column(
        UUID(as_uuid=True),
        ForeignKey("llm_instance.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(String, nullable=False, index=True)
    settings = Column(JSON, nullable=False)
    scope = Column(SQLAlchemyEnum(LLMScope, name="llmscope"), nullable=False)
    status = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    llm_instance = relationship("LLMInstance", back_populates="references")
