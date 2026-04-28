"""SQLAlchemy models for workspace invitations and memberships."""

from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..base.models import BaseModel

INVITATION_STATUS_PENDING = "pending"
INVITATION_STATUS_ACCEPTED = "accepted"
INVITATION_STATUS_REVOKED = "revoked"


class WorkspaceInvitation(BaseModel):
    """A pending or resolved invitation to join a workspace.

    Token is sha256-hashed at rest. The plaintext token is returned to
    the caller exactly once, on create. ``email`` is metadata only — not
    used for security checks. The single security primitive is the
    token; whoever holds it (and is authenticated) can accept once.
    """

    __tablename__ = "workspace_invitations"

    workspace_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    invited_by: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=INVITATION_STATUS_PENDING
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    accepted_by_user_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    def is_expired(self, now: datetime) -> bool:
        return now >= self.expires_at


class WorkspaceMembership(BaseModel):
    """Accepted membership of a user in a workspace.

    Uses BaseModel's UUID id so the table follows the same conventions
    as the rest of the codebase. The (workspace_id, user_id) pair is
    enforced unique at the application level via repository helpers and
    will be enforced by an index in a follow-up migration if churn
    requires it.
    """

    __tablename__ = "workspace_memberships"

    workspace_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    invitation_id: Mapped[str | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
