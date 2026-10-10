"""The link table between messenger accounts and platform users."""

from datetime import datetime

from sqlalchemy import DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from ..base.models import BaseModel

TELEGRAM = "telegram"

#: The person proved control of the account from inside the messenger.
METHOD_PAIRING = "pairing"


class UserExternalIdentity(BaseModel):
    """A messenger account recognised as a platform user.

    Scoped to the user, not to a workspace, like ``WorkspaceMembership``: the
    account belongs to the person wherever they work. Kept here rather than in
    the IdP because the IdP records how a person signs in, cannot be searched
    by an arbitrary trait, and under enterprise SSO is not ours to write.

    ``external_id`` is the provider's stable account id (Telegram ``from.id``),
    never a username, which can be changed and taken by someone else. At most
    one live link per account; a revoked link keeps its row for the audit.
    """

    __tablename__ = "user_external_identities"

    user_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    method: Mapped[str] = mapped_column(String(32), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


Index(
    "uq_user_external_identities_live",
    UserExternalIdentity.provider,
    UserExternalIdentity.external_id,
    unique=True,
    postgresql_where=UserExternalIdentity.revoked_at.is_(None),
    sqlite_where=UserExternalIdentity.revoked_at.is_(None),
)
