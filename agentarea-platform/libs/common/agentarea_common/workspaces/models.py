"""SQLAlchemy models for workspace invitations and memberships."""

from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..base.models import BaseModel

INVITATION_STATUS_PENDING = "pending"
INVITATION_STATUS_ACCEPTED = "accepted"
INVITATION_STATUS_REVOKED = "revoked"

WORKSPACE_TYPE_PERSONAL = "personal"
WORKSPACE_TYPE_SHARED = "shared"


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


class Workspace(BaseModel):
    """A workspace: the tenancy / isolation boundary for scoped resources.

    Reifies what used to be an opaque ``workspace_id`` string into a real
    row. Two flavours, distinguished by ``type``:

    - ``personal``: auto-provisioned per user; ``id`` equals the user's
      id so existing data tagged with ``workspace_id == user_id`` keeps
      working without a backfill.
    - ``shared``: created explicitly; ``id`` is a generated uuid string.

    ``id`` is a ``String`` (not BaseModel's UUID) precisely so a personal
    workspace can reuse the user's id. No foreign keys from scoped tables
    point here yet (additive table), and there is intentionally no
    ``parent_org_id`` — the organization layer is deferred until billing
    or SSO concretely require it.
    """

    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    type: Mapped[str] = mapped_column(
        String(20), nullable=False, default=WORKSPACE_TYPE_PERSONAL
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    @property
    def is_personal(self) -> bool:
        return self.type == WORKSPACE_TYPE_PERSONAL
