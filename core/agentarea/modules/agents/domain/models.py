from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, String, Boolean
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from agentarea.common.base.models import BaseModel


class Agent(BaseModel):
    __tablename__ = "agents"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    description: Mapped[str] = mapped_column(String, nullable=True)
    instruction: Mapped[str] = mapped_column(String, nullable=True)
    model_id: Mapped[str] = mapped_column(String, nullable=True)
    tools_config: Mapped[dict] = mapped_column(JSON, nullable=True)
    events_config: Mapped[dict] = mapped_column(JSON, nullable=True)
    planning: Mapped[bool] = mapped_column(Boolean, nullable=True)
