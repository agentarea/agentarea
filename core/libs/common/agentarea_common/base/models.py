from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import Column, DateTime, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class BaseModel(DeclarativeBase):
    """Base model for all database models."""

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    created_at = Column(DateTime, nullable=False, default=datetime.now)
    updated_at = Column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)

    def __repr__(self) -> str:
        """Return a string representation of the model."""
        return f"<{self.__class__.__name__} {self.id}>"

    def to_dict(self) -> dict[str, Any]:
        """Convert model to dictionary."""
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}


class WorkspaceAwareMixin:
    """Mixin to add workspace awareness to models."""

    user_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    workspace_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    def is_owned_by_user(self, user_id: str) -> bool:
        """Check if this record belongs to the specified user."""
        return self.user_id == user_id

    def is_in_workspace(self, workspace_id: str) -> bool:
        """Check if this record belongs to the specified workspace."""
        return self.workspace_id == workspace_id

    def belongs_to_user_in_workspace(self, user_id: str, workspace_id: str) -> bool:
        """Check if this record belongs to the specified user in the specified workspace."""
        return self.user_id == user_id and self.workspace_id == workspace_id


class WorkspaceScopedMixin:
    """Mixin for workspace-scoped resources with audit trail."""

    workspace_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    def is_in_workspace(self, workspace_id: str) -> bool:
        """Check if this record belongs to the specified workspace."""
        return self.workspace_id == workspace_id

    def is_created_by_user(self, user_id: str) -> bool:
        """Check if this record was created by the specified user."""
        return self.created_by == user_id

    def belongs_to_workspace(self, workspace_id: str) -> bool:
        """Check if this record belongs to the specified workspace."""
        return self.workspace_id == workspace_id


class SoftDeleteMixin:
    """Mixin to add soft delete functionality to models."""

    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)

    def soft_delete(self) -> None:
        """Mark this record as deleted."""
        self.deleted_at = datetime.now()

    def restore(self) -> None:
        """Restore this record from soft delete."""
        self.deleted_at = None

    @property
    def is_deleted(self) -> bool:
        """Check if this record is soft deleted."""
        return self.deleted_at is not None


class AuditMixin:
    """Mixin to add audit fields to models."""

    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    # updated_by: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)

    def set_created_by(self, user_id: str) -> None:
        """Set the user who created this record."""
        self.created_by = user_id

    def set_updated_by(self, user_id: str) -> None:
        """Set the user who last updated this record."""
        self.updated_by = user_id
