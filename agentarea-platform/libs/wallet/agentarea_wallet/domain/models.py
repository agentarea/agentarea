"""ORM models for the wallet domain."""

from agentarea_common.base.models import BaseModel, WorkspaceScopedMixin
from sqlalchemy import JSON, Float, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column


class AgentWallet(BaseModel, WorkspaceScopedMixin):
    """Wallet associated with an agent, supporting x402 and/or MPP payment protocols."""

    __tablename__ = "agent_wallets"
    __table_args__ = (
        UniqueConstraint("agent_id", "workspace_id", name="uq_agent_wallet_per_workspace"),
    )

    agent_id = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("agents.id"), nullable=False, index=True
    )
    wallet_type: Mapped[str] = mapped_column(String, nullable=False)  # "x402", "mpp", "dual"
    x402_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    mpp_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    credentials_secret_id: Mapped[str | None] = mapped_column(String, nullable=True)
    service_budget_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    service_budget_period: Mapped[str] = mapped_column(
        String, nullable=False, default="execution"
    )  # "execution", "daily", "monthly"
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="active"
    )  # "active", "disabled"


class PaymentRecord(BaseModel, WorkspaceScopedMixin):
    """Record of a single payment made by an agent."""

    __tablename__ = "payment_records"

    wallet_id = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("agent_wallets.id"), nullable=False, index=True
    )
    agent_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    execution_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    protocol: Mapped[str] = mapped_column(String, nullable=False)  # "x402", "mpp"
    amount_usd: Mapped[float] = mapped_column(Float, nullable=False)
    recipient: Mapped[str] = mapped_column(String, nullable=False)
    tx_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    tool_name: Mapped[str] = mapped_column(String, nullable=False)
    tool_call_id: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="pending"
    )  # "completed", "failed", "pending"
    error_message: Mapped[str | None] = mapped_column(String, nullable=True)
    protocol_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
