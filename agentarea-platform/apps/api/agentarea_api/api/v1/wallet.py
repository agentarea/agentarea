"""Agent Wallet API endpoints for managing payment wallets and viewing payment history."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from agentarea_api.api.deps.services import BaseSecretManagerDep, DatabaseSessionDep
from agentarea_common.auth.dependencies import UserContextDep
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agents/{agent_id}/wallet", tags=["wallet"])


# ---------------------------------------------------------------------------
# Pydantic request / response schemas
# ---------------------------------------------------------------------------


class X402ConfigSchema(BaseModel):
    network: str = "eip155:8453"
    facilitator_url: str = "https://x402.org/facilitator"
    scheme: str = "exact"
    signer_type: str = "evm"


class MPPConfigSchema(BaseModel):
    payment_method_types: list[str] = Field(default_factory=lambda: ["charge"])
    session_budget_usd: float = 10.0
    stripe_profile_id: str | None = None


class WalletCredentialsSchema(BaseModel):
    x402_private_key: str | None = None
    mpp_tempo_key: str | None = None


class CreateWalletRequest(BaseModel):
    wallet_type: str  # "x402", "mpp", "dual"
    x402_config: X402ConfigSchema | None = None
    mpp_config: MPPConfigSchema | None = None
    credentials: WalletCredentialsSchema | None = None
    service_budget_usd: float = 0.0
    service_budget_period: str = "execution"  # "execution", "daily", "monthly"


class UpdateWalletRequest(BaseModel):
    wallet_type: str | None = None
    x402_config: X402ConfigSchema | None = None
    mpp_config: MPPConfigSchema | None = None
    credentials: WalletCredentialsSchema | None = None
    service_budget_usd: float | None = None
    service_budget_period: str | None = None
    status: str | None = None


class FundWalletRequest(BaseModel):
    service_budget_usd: float


class WalletResponse(BaseModel):
    id: str
    agent_id: str
    wallet_type: str
    x402_config: dict[str, Any] | None = None
    mpp_config: dict[str, Any] | None = None
    has_credentials: bool = False
    service_budget_usd: float
    service_budget_period: str
    status: str
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class WalletBalanceResponse(BaseModel):
    service_budget_usd: float
    service_budget_period: str
    total_spent_current_period: float
    remaining: float


class PaymentRecordResponse(BaseModel):
    id: str
    agent_id: str
    execution_id: str
    protocol: str
    amount_usd: float
    recipient: str
    tx_hash: str | None = None
    tool_name: str
    tool_call_id: str
    status: str
    error_message: str | None = None
    protocol_metadata: dict[str, Any] | None = None
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


class PaginatedPaymentsResponse(BaseModel):
    items: list[PaymentRecordResponse]
    total: int
    page: int
    page_size: int


# ---------------------------------------------------------------------------
# Dependency: get WalletService
# ---------------------------------------------------------------------------


async def get_wallet_service(
    db_session: DatabaseSessionDep,
    user_context: UserContextDep,
    secret_manager: BaseSecretManagerDep,
):
    """Get a WalletService instance for the current request."""
    from agentarea_wallet.application.wallet_service import WalletService
    from agentarea_wallet.infrastructure.repository import (
        PaymentRecordRepository,
        WalletRepository,
    )

    wallet_repo = WalletRepository(db_session, user_context)
    payment_repo = PaymentRecordRepository(db_session, user_context)
    return WalletService(
        wallet_repository=wallet_repo,
        payment_repository=payment_repo,
        secret_manager=secret_manager,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("", status_code=201, response_model=WalletResponse)
async def create_wallet(
    agent_id: UUID,
    request: CreateWalletRequest,
    wallet_service=Depends(get_wallet_service),
):
    """Create a wallet for an agent."""
    from agentarea_wallet.domain.exceptions import WalletAlreadyExistsError

    try:
        wallet = await wallet_service.create_wallet(
            agent_id=str(agent_id),
            wallet_type=request.wallet_type,
            x402_config=request.x402_config.model_dump() if request.x402_config else None,
            mpp_config=request.mpp_config.model_dump() if request.mpp_config else None,
            credentials=request.credentials.model_dump(exclude_none=True)
            if request.credentials
            else None,
            service_budget_usd=request.service_budget_usd,
            service_budget_period=request.service_budget_period,
        )
        return _wallet_to_response(wallet)
    except WalletAlreadyExistsError:
        raise HTTPException(
            status_code=409, detail="Wallet already exists for this agent"
        ) from None
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None


@router.get("", response_model=WalletResponse)
async def get_wallet(
    agent_id: UUID,
    wallet_service=Depends(get_wallet_service),
):
    """Get wallet configuration for an agent (no decrypted credentials)."""
    from agentarea_wallet.domain.exceptions import WalletNotFoundError

    try:
        wallet = await wallet_service.get_wallet(str(agent_id))
        return _wallet_to_response(wallet)
    except WalletNotFoundError:
        raise HTTPException(status_code=404, detail="No wallet configured for this agent") from None


@router.put("", response_model=WalletResponse)
async def update_wallet(
    agent_id: UUID,
    request: UpdateWalletRequest,
    wallet_service=Depends(get_wallet_service),
):
    """Update wallet configuration."""
    from agentarea_wallet.domain.exceptions import WalletNotFoundError

    try:
        updates = request.model_dump(exclude_none=True)
        credentials = updates.pop("credentials", None)

        # Convert nested schemas to dicts
        if "x402_config" in updates and updates["x402_config"] is not None:
            updates["x402_config"] = (
                updates["x402_config"]
                if isinstance(updates["x402_config"], dict)
                else updates["x402_config"].model_dump()
            )
        if "mpp_config" in updates and updates["mpp_config"] is not None:
            updates["mpp_config"] = (
                updates["mpp_config"]
                if isinstance(updates["mpp_config"], dict)
                else updates["mpp_config"].model_dump()
            )

        wallet = await wallet_service.update_wallet(
            agent_id=str(agent_id),
            credentials=credentials,
            **updates,
        )
        return _wallet_to_response(wallet)
    except WalletNotFoundError:
        raise HTTPException(status_code=404, detail="No wallet configured for this agent") from None
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None


@router.delete("", status_code=204)
async def delete_wallet(
    agent_id: UUID,
    wallet_service=Depends(get_wallet_service),
):
    """Delete wallet and associated credentials."""
    from agentarea_wallet.domain.exceptions import WalletNotFoundError

    try:
        await wallet_service.delete_wallet(str(agent_id))
    except WalletNotFoundError:
        raise HTTPException(status_code=404, detail="No wallet configured for this agent") from None


@router.get("/balance", response_model=WalletBalanceResponse)
async def get_wallet_balance(
    agent_id: UUID,
    wallet_service=Depends(get_wallet_service),
):
    """Get current service budget status."""
    from agentarea_wallet.domain.exceptions import WalletNotFoundError

    try:
        wallet = await wallet_service.get_wallet(str(agent_id))
        spent = await wallet_service.get_total_spent_current_period(str(agent_id))
        remaining = max(0.0, wallet.service_budget_usd - spent)

        return WalletBalanceResponse(
            service_budget_usd=wallet.service_budget_usd,
            service_budget_period=wallet.service_budget_period,
            total_spent_current_period=spent,
            remaining=remaining,
        )
    except WalletNotFoundError:
        raise HTTPException(status_code=404, detail="No wallet configured for this agent") from None


@router.get("/payments", response_model=PaginatedPaymentsResponse)
async def get_payment_history(
    agent_id: UUID,
    wallet_service=Depends(get_wallet_service),
    protocol: str | None = Query(None, description="Filter by protocol (x402, mpp)"),
    status: str | None = Query(None, description="Filter by status"),
    from_date: datetime | None = Query(None, description="Filter from date"),
    to_date: datetime | None = Query(None, description="Filter to date"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    """Get paginated payment history for an agent."""
    offset = (page - 1) * page_size
    payments, total = await wallet_service.get_payment_history(
        agent_id=str(agent_id),
        protocol=protocol,
        status=status,
        from_date=from_date,
        to_date=to_date,
        limit=page_size,
        offset=offset,
    )

    return PaginatedPaymentsResponse(
        items=[_payment_to_response(p) for p in payments],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/fund", response_model=WalletResponse)
async def fund_wallet(
    agent_id: UUID,
    request: FundWalletRequest,
    wallet_service=Depends(get_wallet_service),
):
    """Update the service budget amount."""
    from agentarea_wallet.domain.exceptions import WalletNotFoundError

    try:
        wallet = await wallet_service.update_wallet(
            agent_id=str(agent_id),
            service_budget_usd=request.service_budget_usd,
        )
        return _wallet_to_response(wallet)
    except WalletNotFoundError:
        raise HTTPException(status_code=404, detail="No wallet configured for this agent") from None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _wallet_to_response(wallet) -> WalletResponse:
    return WalletResponse(
        id=str(wallet.id),
        agent_id=str(wallet.agent_id),
        wallet_type=wallet.wallet_type,
        x402_config=wallet.x402_config,
        mpp_config=wallet.mpp_config,
        has_credentials=wallet.credentials_secret_id is not None,
        service_budget_usd=wallet.service_budget_usd,
        service_budget_period=wallet.service_budget_period,
        status=wallet.status,
        created_at=wallet.created_at,
        updated_at=wallet.updated_at,
    )


def _payment_to_response(payment) -> PaymentRecordResponse:
    return PaymentRecordResponse(
        id=str(payment.id),
        agent_id=payment.agent_id,
        execution_id=payment.execution_id,
        protocol=payment.protocol,
        amount_usd=payment.amount_usd,
        recipient=payment.recipient,
        tx_hash=payment.tx_hash,
        tool_name=payment.tool_name,
        tool_call_id=payment.tool_call_id,
        status=payment.status,
        error_message=payment.error_message,
        protocol_metadata=payment.protocol_metadata,
        created_at=payment.created_at,
    )
