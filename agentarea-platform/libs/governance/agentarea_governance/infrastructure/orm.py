"""ORM models for persisted governance policy rules."""

from typing import Any

from agentarea_common.base.models import BaseModel, WorkspaceScopedMixin
from sqlalchemy import JSON, Boolean, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

JSONB_TYPE = JSONB().with_variant(JSON(), "sqlite")


class PolicyRuleORM(BaseModel, WorkspaceScopedMixin):
    """A single unified governance rule scoped to a subject."""

    __tablename__ = "policies"
    __table_args__ = (
        Index(
            "ix_policies_workspace_subject",
            "workspace_id",
            "subject_type",
            "subject_id",
        ),
    )

    subject_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    subject_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    target: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    effect: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB_TYPE, nullable=False, default=dict)
    condition: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
