"""Which channel brought each sign-up (wiki ADR-0047)."""

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from ..base.models import BaseModel


class SignupAttribution(BaseModel):
    """One identity's sign-up: its method and the first touch of the visit that brought it.

    Belongs to no workspace, and is keyed by the identity rather than a surrogate id,
    so a replayed registration hook finds its first row. ``created_at`` is when the
    identity was created.
    """

    __tablename__ = "signup_attributions"

    id = None  # type: ignore[assignment]
    identity_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    method: Mapped[str | None] = mapped_column(String(16), nullable=True)
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    referrer_host: Mapped[str | None] = mapped_column(String(64), nullable=True)
    landing_host: Mapped[str | None] = mapped_column(String(64), nullable=True)
    landing_path: Mapped[str | None] = mapped_column(String(64), nullable=True)
    utm_source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    utm_medium: Mapped[str | None] = mapped_column(String(64), nullable=True)
    utm_campaign: Mapped[str | None] = mapped_column(String(64), nullable=True)
