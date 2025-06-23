from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import Column, DateTime
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import DeclarativeBase


class BaseModel(DeclarativeBase):
    """Base model for all database models."""

    id = Column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    created_at = Column(DateTime, nullable=False, default=datetime.now)
    updated_at = Column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} {self.id}>"

    def to_dict(self) -> dict[str, Any]:
        """Convert model to dictionary."""
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}
