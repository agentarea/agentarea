"""Event-specific ORM base class without updated_at/created_at to match existing schema."""

from typing import Any
from uuid import uuid4

from agentarea_common.base.models import BaseModel
from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase


class EventBaseModel(DeclarativeBase):
    """Base model for event tables that are append-only and never updated.

    We intentionally avoid created_at/updated_at columns to match current schema
    and keep events immutable without requiring migrations.
    """

    # Share the same MetaData as the common BaseModel so Alembic autogenerate sees one metadata
    metadata = BaseModel.metadata

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)

    def __repr__(self) -> str:
        """Return a string representation of the model."""
        return f"<{self.__class__.__name__} {self.id}>"

    def to_dict(self) -> dict[str, Any]:
        """Convert model to dictionary."""
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}
