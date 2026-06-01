"""Repositories for the wallet domain."""

import logging
from datetime import UTC, datetime
from uuid import UUID

from agentarea_common.auth.context import UserContext
from agentarea_common.base.workspace_scoped_repository import WorkspaceScopedRepository
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agentarea_wallet.domain.models import AgentWallet, PaymentRecord

logger = logging.getLogger(__name__)


class WalletRepository(WorkspaceScopedRepository[AgentWallet]):
    """Repository for AgentWallet records."""

    def __init__(self, session: AsyncSession, user_context: UserContext):
        super().__init__(session, AgentWallet, user_context)

    async def get_by_agent_id(self, agent_id: UUID | str) -> AgentWallet | None:
        """Get the wallet for a specific agent within the current workspace.

        Args:
            agent_id: The agent UUID.

        Returns:
            The wallet if found, None otherwise.
        """
        query = (
            select(AgentWallet)
            .where(AgentWallet.agent_id == agent_id)
            .where(self._get_workspace_filter())
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def list_budget_exhausted(self) -> list[AgentWallet]:
        """List wallets in the current workspace whose period spend has hit the cap.

        Live computation, no events. Mirrors the live-query pattern used by
        the existing service-budget guard. Wallets with budget_period
        ``execution`` are skipped — those caps are per-execution and don't
        map to a workspace-level "exhausted" notion.
        """
        query = (
            select(AgentWallet)
            .where(self._get_workspace_filter())
            .where(AgentWallet.status == "active")
            .where(AgentWallet.service_budget_usd > 0)
            .where(AgentWallet.service_budget_period.in_(["daily", "monthly"]))
        )
        result = await self.session.execute(query)
        wallets = list(result.scalars().all())

        if not wallets:
            return []

        # Compute spent per period via a small per-wallet query — keeps logic
        # simple and avoids JSON gymnastics. Workspaces with thousands of
        # active wallets should revisit with a window query.
        today = datetime.now(UTC).date()
        daily_start = datetime(today.year, today.month, today.day)
        monthly_start = datetime(today.year, today.month, 1)

        exhausted: list[AgentWallet] = []
        for wallet in wallets:
            period_start = daily_start if wallet.service_budget_period == "daily" else monthly_start
            spent_q = (
                select(func.coalesce(func.sum(PaymentRecord.amount_usd), 0.0))
                .where(PaymentRecord.agent_id == str(wallet.agent_id))
                .where(PaymentRecord.status == "completed")
                .where(PaymentRecord.created_at >= period_start)
                .where(PaymentRecord.workspace_id == wallet.workspace_id)
            )
            spent = float((await self.session.execute(spent_q)).scalar() or 0.0)
            if spent >= float(wallet.service_budget_usd):
                exhausted.append(wallet)
        return exhausted


class PaymentRecordRepository(WorkspaceScopedRepository[PaymentRecord]):
    """Repository for PaymentRecord records."""

    def __init__(self, session: AsyncSession, user_context: UserContext):
        super().__init__(session, PaymentRecord, user_context)

    async def list_by_agent(
        self,
        agent_id: str,
        protocol: str | None = None,
        status: str | None = None,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[PaymentRecord]:
        """List payment records for a specific agent with optional filters.

        Args:
            agent_id: The agent identifier.
            protocol: Optional protocol filter ("x402" or "mpp").
            status: Optional status filter ("pending", "completed", "failed").
            from_date: Optional lower bound on created_at.
            to_date: Optional upper bound on created_at.
            limit: Max records to return.
            offset: Records to skip.

        Returns:
            List of matching PaymentRecord objects.
        """
        query = (
            select(PaymentRecord)
            .where(PaymentRecord.agent_id == agent_id)
            .where(self._get_workspace_filter())
        )

        if protocol is not None:
            query = query.where(PaymentRecord.protocol == protocol)
        if status is not None:
            query = query.where(PaymentRecord.status == status)
        if from_date is not None:
            query = query.where(PaymentRecord.created_at >= from_date)
        if to_date is not None:
            query = query.where(PaymentRecord.created_at <= to_date)

        query = query.offset(offset).limit(limit)

        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def sum_by_execution(self, agent_id: str, execution_id: str) -> float:
        """Return total amount_usd spent by an agent within an execution.

        Args:
            agent_id: The agent identifier.
            execution_id: The execution identifier.

        Returns:
            Sum of amount_usd for completed payments in the execution.
        """
        query = (
            select(func.coalesce(func.sum(PaymentRecord.amount_usd), 0.0))
            .where(PaymentRecord.agent_id == agent_id)
            .where(PaymentRecord.execution_id == execution_id)
            .where(PaymentRecord.status == "completed")
            .where(self._get_workspace_filter())
        )
        result = await self.session.execute(query)
        return float(result.scalar() or 0.0)

    async def sum_by_period(self, agent_id: str, budget_period: str) -> float:
        """Return total amount_usd spent by an agent in the current budget period.

        Args:
            agent_id: The agent identifier.
            budget_period: One of "daily" or "monthly". "execution" is not handled here.

        Returns:
            Sum of amount_usd for completed payments in the current period.
        """
        query = (
            select(func.coalesce(func.sum(PaymentRecord.amount_usd), 0.0))
            .where(PaymentRecord.agent_id == agent_id)
            .where(PaymentRecord.status == "completed")
            .where(self._get_workspace_filter())
        )

        today = datetime.now(UTC).date()
        if budget_period == "daily":
            period_start = datetime(today.year, today.month, today.day)
            query = query.where(PaymentRecord.created_at >= period_start)
        elif budget_period == "monthly":
            period_start = datetime(today.year, today.month, 1)
            query = query.where(PaymentRecord.created_at >= period_start)

        result = await self.session.execute(query)
        return float(result.scalar() or 0.0)
