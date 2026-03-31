"""Wallet service tests with mocked repositories and secret manager."""

import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from agentarea_wallet.application.wallet_service import WalletService
from agentarea_wallet.domain.exceptions import WalletAlreadyExistsError, WalletNotFoundError


def _make_wallet(**overrides):
    """Create a mock wallet object."""
    wallet = MagicMock()
    wallet.id = overrides.get("id", uuid4())
    wallet.agent_id = overrides.get("agent_id", uuid4())
    wallet.wallet_type = overrides.get("wallet_type", "dual")
    wallet.x402_config = overrides.get("x402_config", {"network": "eip155:8453"})
    wallet.mpp_config = overrides.get("mpp_config", {"payment_method_types": ["charge"]})
    wallet.credentials_secret_id = overrides.get("credentials_secret_id", None)
    wallet.service_budget_usd = overrides.get("service_budget_usd", 5.0)
    wallet.service_budget_period = overrides.get("service_budget_period", "execution")
    wallet.status = overrides.get("status", "active")
    wallet.created_at = datetime.now()
    wallet.updated_at = datetime.now()
    return wallet


def _make_payment(**overrides):
    """Create a mock payment record."""
    record = MagicMock()
    record.id = overrides.get("id", uuid4())
    record.agent_id = overrides.get("agent_id", "agent_1")
    record.execution_id = overrides.get("execution_id", "exec_1")
    record.protocol = overrides.get("protocol", "x402")
    record.amount_usd = overrides.get("amount_usd", 0.01)
    record.recipient = overrides.get("recipient", "0xabc")
    record.tx_hash = overrides.get("tx_hash", "0xdef")
    record.tool_name = overrides.get("tool_name", "weather_api")
    record.tool_call_id = overrides.get("tool_call_id", "tc_1")
    record.status = overrides.get("status", "completed")
    record.error_message = overrides.get("error_message", None)
    record.protocol_metadata = overrides.get("protocol_metadata", None)
    record.created_at = datetime.now()
    return record


@pytest.fixture
def wallet_repo():
    repo = AsyncMock()
    return repo


@pytest.fixture
def payment_repo():
    repo = AsyncMock()
    return repo


@pytest.fixture
def secret_manager():
    sm = AsyncMock()
    return sm


@pytest.fixture
def service(wallet_repo, payment_repo, secret_manager):
    return WalletService(
        wallet_repository=wallet_repo,
        payment_repository=payment_repo,
        secret_manager=secret_manager,
    )


# ------------------------------------------------------------------
# create_wallet
# ------------------------------------------------------------------


class TestCreateWallet:
    @pytest.mark.asyncio
    async def test_create_wallet_happy_path(self, service, wallet_repo):
        wallet_repo.get_by_agent_id.return_value = None
        created = _make_wallet()
        wallet_repo.create.return_value = created

        result = await service.create_wallet(
            agent_id="agent_1",
            wallet_type="dual",
            x402_config={"network": "eip155:8453"},
            mpp_config={"payment_method_types": ["charge"]},
            service_budget_usd=5.0,
        )

        assert result == created
        wallet_repo.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_wallet_with_credentials(self, service, wallet_repo, secret_manager):
        wallet_repo.get_by_agent_id.return_value = None
        wallet_repo.create.return_value = _make_wallet(credentials_secret_id="wallet_creds_agent_1")

        await service.create_wallet(
            agent_id="agent_1",
            wallet_type="x402",
            x402_config={"network": "eip155:8453"},
            credentials={"x402_private_key": "0xsecret"},
            service_budget_usd=5.0,
        )

        secret_manager.set_secret.assert_called_once_with(
            "wallet_creds_agent_1",
            json.dumps({"x402_private_key": "0xsecret"}),
        )

    @pytest.mark.asyncio
    async def test_create_wallet_duplicate_raises(self, service, wallet_repo):
        wallet_repo.get_by_agent_id.return_value = _make_wallet()

        with pytest.raises(WalletAlreadyExistsError):
            await service.create_wallet(
                agent_id="agent_1",
                wallet_type="x402",
                x402_config={"network": "eip155:8453"},
            )

    @pytest.mark.asyncio
    async def test_create_wallet_validation_error(self, service, wallet_repo):
        wallet_repo.get_by_agent_id.return_value = None

        with pytest.raises(ValueError, match="x402_config"):
            await service.create_wallet(
                agent_id="agent_1",
                wallet_type="x402",
                x402_config=None,
            )


# ------------------------------------------------------------------
# get_wallet
# ------------------------------------------------------------------


class TestGetWallet:
    @pytest.mark.asyncio
    async def test_get_wallet_found(self, service, wallet_repo):
        wallet = _make_wallet()
        wallet_repo.get_by_agent_id.return_value = wallet

        result = await service.get_wallet("agent_1")
        assert result == wallet

    @pytest.mark.asyncio
    async def test_get_wallet_not_found(self, service, wallet_repo):
        wallet_repo.get_by_agent_id.return_value = None

        with pytest.raises(WalletNotFoundError):
            await service.get_wallet("agent_1")


# ------------------------------------------------------------------
# update_wallet
# ------------------------------------------------------------------


class TestUpdateWallet:
    @pytest.mark.asyncio
    async def test_update_fields(self, service, wallet_repo):
        wallet = _make_wallet()
        wallet_repo.get_by_agent_id.return_value = wallet
        wallet_repo.update.return_value = wallet

        result = await service.update_wallet(
            agent_id="agent_1",
            service_budget_usd=10.0,
        )

        assert result == wallet
        wallet_repo.update.assert_called_once()
        call_kwargs = wallet_repo.update.call_args
        assert call_kwargs[1]["service_budget_usd"] == 10.0

    @pytest.mark.asyncio
    async def test_update_credentials(self, service, wallet_repo, secret_manager):
        wallet = _make_wallet()
        wallet_repo.get_by_agent_id.return_value = wallet
        wallet_repo.update.return_value = wallet

        await service.update_wallet(
            agent_id="agent_1",
            credentials={"x402_private_key": "0xnew"},
        )

        secret_manager.set_secret.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_not_found(self, service, wallet_repo):
        wallet_repo.get_by_agent_id.return_value = None

        with pytest.raises(WalletNotFoundError):
            await service.update_wallet(agent_id="agent_1", service_budget_usd=10.0)


# ------------------------------------------------------------------
# delete_wallet
# ------------------------------------------------------------------


class TestDeleteWallet:
    @pytest.mark.asyncio
    async def test_delete_with_credentials(self, service, wallet_repo, secret_manager):
        wallet = _make_wallet(credentials_secret_id="wallet_creds_agent_1")
        wallet_repo.get_by_agent_id.return_value = wallet

        await service.delete_wallet("agent_1")

        secret_manager.delete_secret.assert_called_once_with("wallet_creds_agent_1")
        wallet_repo.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_without_credentials(self, service, wallet_repo, secret_manager):
        wallet = _make_wallet(credentials_secret_id=None)
        wallet_repo.get_by_agent_id.return_value = wallet

        await service.delete_wallet("agent_1")

        secret_manager.delete_secret.assert_not_called()
        wallet_repo.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_not_found(self, service, wallet_repo):
        wallet_repo.get_by_agent_id.return_value = None

        with pytest.raises(WalletNotFoundError):
            await service.delete_wallet("agent_1")


# ------------------------------------------------------------------
# Budget
# ------------------------------------------------------------------


class TestBudget:
    @pytest.mark.asyncio
    async def test_get_service_budget_remaining_execution(self, service, wallet_repo, payment_repo):
        wallet = _make_wallet(service_budget_usd=5.0, service_budget_period="execution")
        wallet_repo.get_by_agent_id.return_value = wallet
        payment_repo.sum_by_execution.return_value = 2.0

        remaining = await service.get_service_budget_remaining("agent_1", "exec_1")
        assert remaining == 3.0

    @pytest.mark.asyncio
    async def test_get_service_budget_remaining_daily(self, service, wallet_repo, payment_repo):
        wallet = _make_wallet(service_budget_usd=10.0, service_budget_period="daily")
        wallet_repo.get_by_agent_id.return_value = wallet
        payment_repo.sum_by_period.return_value = 7.5

        remaining = await service.get_service_budget_remaining("agent_1", "exec_1")
        assert remaining == 2.5

    @pytest.mark.asyncio
    async def test_get_total_spent_current_period(self, service, wallet_repo, payment_repo):
        wallet = _make_wallet(service_budget_period="daily")
        wallet_repo.get_by_agent_id.return_value = wallet
        payment_repo.sum_by_period.return_value = 3.50

        spent = await service.get_total_spent_current_period("agent_1")
        assert spent == 3.50


# ------------------------------------------------------------------
# Payment history
# ------------------------------------------------------------------


class TestPaymentHistory:
    @pytest.mark.asyncio
    async def test_get_payment_history_returns_tuple(self, service, payment_repo):
        records = [_make_payment(), _make_payment()]
        payment_repo.list_by_agent.return_value = records
        payment_repo.count.return_value = 50

        result, total = await service.get_payment_history(agent_id="agent_1")
        assert len(result) == 2
        assert total == 50

    @pytest.mark.asyncio
    async def test_record_payment(self, service, payment_repo):
        record = _make_payment()
        payment_repo.create.return_value = record

        result = await service.record_payment(
            wallet_id=uuid4(),
            agent_id="agent_1",
            execution_id="exec_1",
            protocol="x402",
            amount_usd=0.01,
            recipient="0xabc",
            tx_hash="0xdef",
            tool_name="weather_api",
            tool_call_id="tc_1",
            status="completed",
        )

        assert result == record
        payment_repo.create.assert_called_once()
