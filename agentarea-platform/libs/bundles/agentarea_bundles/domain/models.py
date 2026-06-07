"""InstalledBundle ORM model.

Provenance + idempotency record: stores the fully-normalized canonical package
(as jsonb) that was installed in a workspace, keyed by package name.
"""

from __future__ import annotations

from typing import Any

from agentarea_common.base.models import BaseModel, WorkspaceScopedMixin
from sqlalchemy import String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class InstalledBundle(BaseModel, WorkspaceScopedMixin):
    """A package that was analyzed/installed into a workspace."""

    __tablename__ = "installed_bundles"

    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="installed")
    # The full normalized Bundle as published; source for re-preview/diff.
    canonical: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    # Map of created/reused entity refs from the last install (kind/key/id/action).
    install_result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    def __repr__(self) -> str:
        """Return a compact string representation."""
        return f"<InstalledBundle {self.name} ({self.id})>"
