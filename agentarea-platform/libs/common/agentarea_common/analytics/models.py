"""The one row that identifies this installation to the collector."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, Index, String, literal_column
from sqlalchemy.orm import Mapped, mapped_column

from ..base.models import BaseModel


class Installation(BaseModel):
    """This installation: its anonymous id and when it last sent a pulse.

    Belongs to no workspace; a unique index on a constant holds it to one row.
    """

    __tablename__ = "installation"
    __table_args__ = (Index("uq_installation_single_row", literal_column("(true)"), unique=True),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid4().hex)
    last_pulse_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
