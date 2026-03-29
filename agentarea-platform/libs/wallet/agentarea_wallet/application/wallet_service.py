"""Wallet application service."""

import json
import logging
from datetime import datetime
from uuid import UUID

from agentarea_common.infrastructure.secret_manager import BaseSecretManager

from agentarea_wallet.domain.exceptions import (
    WalletAlreadyExistsError,
    WalletNotFoundError,
)
from agentarea_wallet.domain.models import AgentWallet, PaymentRecord
from agentarea_wallet.infrastructure.repository import PaymentRecordRepository, WalletRepository

logger = logging.getLogger(__name__)


class WalletService:
    """Application service for managing agent wallets and payment records."""

    def __init__(
        self,
        wallet_repository: WalletRepository,
        payment_repository: PaymentRecordRepository,
        secret_manager: BaseSecretManager,
    ):
        self._wallets = wallet_repository
        self._payments = payment_repository
        self._secrets = secret_manager

    # ------------------------------------------------------------------
    # Wallet CRUD
    # ------------------------------------------------------------------

    async def create_wallet(
        self,
        agent_id: UUID | str,
        wallet_type: str,
        x402_config: dict | None = None,
        mpp_config: dict | None = None,
        credentials: dict | None = None,
        service_budget_usd: float = 0.0,
        service_budget_period: str = "execution",
    ) -> AgentWallet:
        """Create a new wallet for an agent.

        Args:
            agent_id: The agent UUID.
            wallet_type: One of "x402", "mpp", "dual".
            x402_config: Required when wallet_type is "x402" or "dual".
            mpp_config: Required when wallet_type is "mpp" or "dual".
            credentials: Optional credentials dict to store in the secret manager.
            service_budget_usd: Service budget cap in USD.
            service_budget_period: Budget reset period ("execution", "daily", "monthly").

        Returns:
            The created AgentWallet.

        Raises:
            WalletAlreadyExistsError: If a wallet already exists for this agent.
            ValueError: If required config is missing for the given wallet_type.
        """
        self._validate_config(wallet_type, x402_config, mpp_config)

        existing = await self._wallets.get_by_agent_id(agent_id)
        if existing is not None:
            raise WalletAlreadyExistsError(
                f"A wallet already exists for agent {agent_id}"
            )

        credentials_secret_id: str | None = None
        if credentials is not None:
            secret_key = f"wallet_creds_{agent_id}"
            await self._secrets.set_secret(secret_key, json.dumps(credentials))
            credentials_secret_id = secret_key
            logger.info("Stored wallet credentials for agent %s", agent_id)

        wallet = await self._wallets.create(
            agent_id=agent_id,
            wallet_type=wallet_type,
            x402_config=x402_config,
            mpp_config=mpp_config,
            credentials_secret_id=credentials_secret_id,
            service_budget_usd=service_budget_usd,
            service_budget_period=service_budget_period,
            status="active",
        )

        logger.info("Created wallet %s for agent %s", wallet.id, agent_id)
        return wallet

    async def get_wallet(self, agent_id: UUID | str) -> AgentWallet:
        """Return the wallet for an agent (no credential decryption).

        Args:
            agent_id: The agent UUID.

        Returns:
            The AgentWallet.

        Raises:
            WalletNotFoundError: If no wallet exists for this agent.
        """
        wallet = await self._wallets.get_by_agent_id(agent_id)
        if wallet is None:
            raise WalletNotFoundError(f"No wallet found for agent {agent_id}")
        return wallet

    async def update_wallet(
        self,
        agent_id: UUID | str,
        wallet_type: str | None = None,
        x402_config: dict | None = None,
        mpp_config: dict | None = None,
        credentials: dict | None = None,
        service_budget_usd: float | None = None,
        service_budget_period: str | None = None,
        status: str | None = None,
    ) -> AgentWallet:
        """Update wallet fields.

        Args:
            agent_id: The agent UUID.
            wallet_type: New wallet type (optional).
            x402_config: New x402 config (optional).
            mpp_config: New MPP config (optional).
            credentials: New credentials dict to re-store in secret manager (optional).
            service_budget_usd: New budget cap (optional).
            service_budget_period: New budget period (optional).
            status: New status (optional).

        Returns:
            The updated AgentWallet.

        Raises:
            WalletNotFoundError: If no wallet exists for this agent.
            ValueError: If required config is missing for the given wallet_type.
        """
        wallet = await self._wallets.get_by_agent_id(agent_id)
        if wallet is None:
            raise WalletNotFoundError(f"No wallet found for agent {agent_id}")

        # Determine the effective wallet_type for validation
        effective_type = wallet_type if wallet_type is not None else wallet.wallet_type
        effective_x402 = x402_config if x402_config is not None else wallet.x402_config
        effective_mpp = mpp_config if mpp_config is not None else wallet.mpp_config
        self._validate_config(effective_type, effective_x402, effective_mpp)

        updates: dict = {}
        if wallet_type is not None:
            updates["wallet_type"] = wallet_type
        if x402_config is not None:
            updates["x402_config"] = x402_config
        if mpp_config is not None:
            updates["mpp_config"] = mpp_config
        if service_budget_usd is not None:
            updates["service_budget_usd"] = service_budget_usd
        if service_budget_period is not None:
            updates["service_budget_period"] = service_budget_period
        if status is not None:
            updates["status"] = status

        if credentials is not None:
            secret_key = f"wallet_creds_{agent_id}"
            await self._secrets.set_secret(secret_key, json.dumps(credentials))
            updates["credentials_secret_id"] = secret_key
            logger.info("Updated wallet credentials for agent %s", agent_id)

        updated = await self._wallets.update(str(wallet.id), **updates)
        if updated is None:
            raise WalletNotFoundError(f"No wallet found for agent {agent_id}")

        logger.info("Updated wallet %s for agent %s", wallet.id, agent_id)
        return updated

    async def delete_wallet(self, agent_id: UUID | str) -> None:
        """Delete the wallet for an agent and its associated secret.

        Args:
            agent_id: The agent UUID.

        Raises:
            WalletNotFoundError: If no wallet exists for this agent.
        """
        wallet = await self._wallets.get_by_agent_id(agent_id)
        if wallet is None:
            raise WalletNotFoundError(f"No wallet found for agent {agent_id}")

        if wallet.credentials_secret_id:
            try:
                delete_fn = getattr(self._secrets, "delete_secret", None)
                if delete_fn is not None:
                    await delete_fn(wallet.credentials_secret_id)
                    logger.info("Deleted credentials secret for agent %s", agent_id)
                else:
                    logger.warning(
                        "Secret manager does not support delete; skipping secret cleanup for agent %s",
                        agent_id,
                    )
            except Exception:
                logger.warning(
                    "Failed to delete credentials secret for agent %s", agent_id, exc_info=True
                )

        await self._wallets.delete(str(wallet.id))
        logger.info("Deleted wallet %s for agent %s", wallet.id, agent_id)

    # ------------------------------------------------------------------
    # Budget
    # ------------------------------------------------------------------

    async def get_service_budget_remaining(
        self, agent_id: UUID | str, execution_id: str
    ) -> float:
        """Compute remaining budget for an agent based on its budget period.

        Args:
            agent_id: The agent UUID.
            execution_id: Current execution identifier (used for "execution" period).

        Returns:
            Remaining budget in USD. Returns 0.0 if no budget is configured (unlimited
            wallets should be checked by the caller — a 0.0 budget means "no budget set").

        Raises:
            WalletNotFoundError: If no wallet exists for this agent.
        """
        wallet = await self.get_wallet(agent_id)

        period = wallet.service_budget_period
        if period == "execution":
            spent = await self._payments.sum_by_execution(str(agent_id), execution_id)
        else:
            spent = await self._payments.sum_by_period(str(agent_id), period)

        remaining = wallet.service_budget_usd - spent
        return max(remaining, 0.0)

    # ------------------------------------------------------------------
    # Payments
    # ------------------------------------------------------------------

    async def record_payment(
        self,
        wallet_id: UUID | str,
        agent_id: str,
        execution_id: str,
        protocol: str,
        amount_usd: float,
        recipient: str,
        tx_hash: str | None,
        tool_name: str,
        tool_call_id: str,
        status: str = "pending",
        error_message: str | None = None,
        protocol_metadata: dict | None = None,
    ) -> PaymentRecord:
        """Create a payment record.

        Args:
            wallet_id: The wallet UUID.
            agent_id: The agent identifier.
            execution_id: The execution identifier.
            protocol: Payment protocol ("x402" or "mpp").
            amount_usd: Amount in USD.
            recipient: Payment recipient address/identifier.
            tx_hash: Transaction hash (optional).
            tool_name: Name of the tool that triggered the payment.
            tool_call_id: Tool call identifier.
            status: Payment status ("pending", "completed", "failed").
            error_message: Error message if payment failed (optional).
            protocol_metadata: Additional protocol-specific metadata (optional).

        Returns:
            The created PaymentRecord.
        """
        record = await self._payments.create(
            wallet_id=wallet_id,
            agent_id=agent_id,
            execution_id=execution_id,
            protocol=protocol,
            amount_usd=amount_usd,
            recipient=recipient,
            tx_hash=tx_hash,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            status=status,
            error_message=error_message,
            protocol_metadata=protocol_metadata,
        )
        logger.info(
            "Recorded payment %s for agent %s execution %s amount=%s",
            record.id,
            agent_id,
            execution_id,
            amount_usd,
        )
        return record

    async def get_payment_history(
        self,
        agent_id: str,
        protocol: str | None = None,
        status: str | None = None,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[PaymentRecord]:
        """Return paginated payment history for an agent.

        Args:
            agent_id: The agent identifier.
            protocol: Optional protocol filter.
            status: Optional status filter.
            from_date: Optional lower bound on created_at.
            to_date: Optional upper bound on created_at.
            limit: Max records to return.
            offset: Records to skip.

        Returns:
            List of PaymentRecord objects.
        """
        return await self._payments.list_by_agent(
            agent_id=agent_id,
            protocol=protocol,
            status=status,
            from_date=from_date,
            to_date=to_date,
            limit=limit,
            offset=offset,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_config(
        wallet_type: str,
        x402_config: dict | None,
        mpp_config: dict | None,
    ) -> None:
        """Validate that required configs are present for the given wallet_type.

        Args:
            wallet_type: One of "x402", "mpp", "dual".
            x402_config: x402 configuration dict.
            mpp_config: MPP configuration dict.

        Raises:
            ValueError: If a required config is missing.
        """
        if wallet_type in ("x402", "dual") and x402_config is None:
            raise ValueError(
                f"x402_config is required for wallet_type '{wallet_type}'"
            )
        if wallet_type in ("mpp", "dual") and mpp_config is None:
            raise ValueError(
                f"mpp_config is required for wallet_type '{wallet_type}'"
            )
