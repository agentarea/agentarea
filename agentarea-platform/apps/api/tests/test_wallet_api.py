"""API endpoint tests for wallet routes with mocked WalletService."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from agentarea_api.api.v1.wallet import ensure_agent_exists, get_wallet_service, router
from agentarea_common.testing.flows import MainFlow
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


def _mock_wallet(**overrides):
    w = MagicMock()
    w.id = overrides.get("id", uuid4())
    w.agent_id = overrides.get("agent_id", uuid4())
    w.wallet_type = overrides.get("wallet_type", "dual")
    w.x402_config = overrides.get("x402_config", {"network": "eip155:8453"})
    w.mpp_config = overrides.get("mpp_config", {"payment_method_types": ["charge"]})
    w.credentials_secret_id = overrides.get("credentials_secret_id", "secret_1")
    w.service_budget_usd = overrides.get("service_budget_usd", 5.0)
    w.service_budget_period = overrides.get("service_budget_period", "execution")
    w.status = overrides.get("status", "active")
    w.created_at = datetime.now()
    w.updated_at = datetime.now()
    return w


def _mock_payment(**overrides):
    p = MagicMock()
    p.id = overrides.get("id", uuid4())
    p.agent_id = overrides.get("agent_id", "agent_1")
    p.execution_id = overrides.get("execution_id", "exec_1")
    p.protocol = overrides.get("protocol", "x402")
    p.amount_usd = overrides.get("amount_usd", 0.01)
    p.recipient = overrides.get("recipient", "0xabc")
    p.tx_hash = overrides.get("tx_hash", "0xdef")
    p.tool_name = overrides.get("tool_name", "weather")
    p.tool_call_id = overrides.get("tool_call_id", "tc_1")
    p.status = overrides.get("status", "completed")
    p.error_message = overrides.get("error_message", None)
    p.protocol_metadata = overrides.get("protocol_metadata", None)
    p.created_at = datetime.now()
    return p


@pytest.fixture
def mock_service():
    return AsyncMock()


@pytest.fixture
def client(mock_service):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_wallet_service] = lambda: mock_service
    app.dependency_overrides[ensure_agent_exists] = lambda: None
    return TestClient(app)


AGENT_ID = str(uuid4())


# ------------------------------------------------------------------
# POST create wallet
# ------------------------------------------------------------------


@pytest.mark.flow(MainFlow.WALLET_PAYMENTS)
class TestCreateWallet:
    def test_create_201(self, client, mock_service):
        mock_service.create_wallet.return_value = _mock_wallet()

        resp = client.post(f"/agents/{AGENT_ID}/wallet", json={
            "wallet_type": "x402",
            "x402_config": {"network": "eip155:8453"},
            "service_budget_usd": 5.0,
            "service_budget_period": "execution",
        })

        assert resp.status_code == 201
        data = resp.json()
        assert data["wallet_type"] == "dual"
        assert data["has_credentials"] is True

    def test_create_409_duplicate(self, client, mock_service):
        from agentarea_wallet.domain.exceptions import WalletAlreadyExistsError
        mock_service.create_wallet.side_effect = WalletAlreadyExistsError("exists")

        resp = client.post(f"/agents/{AGENT_ID}/wallet", json={
            "wallet_type": "x402",
            "x402_config": {"network": "eip155:8453"},
        })

        assert resp.status_code == 409

    def test_create_400_validation(self, client, mock_service):
        mock_service.create_wallet.side_effect = ValueError("x402_config required")

        resp = client.post(f"/agents/{AGENT_ID}/wallet", json={
            "wallet_type": "x402",
        })

        assert resp.status_code == 400
        assert "x402_config" in resp.json()["detail"]


# ------------------------------------------------------------------
# GET wallet
# ------------------------------------------------------------------


class TestGetWallet:
    def test_get_200(self, client, mock_service):
        mock_service.get_wallet.return_value = _mock_wallet()

        resp = client.get(f"/agents/{AGENT_ID}/wallet")
        assert resp.status_code == 200
        assert "wallet_type" in resp.json()

    def test_get_404(self, client, mock_service):
        from agentarea_wallet.domain.exceptions import WalletNotFoundError
        mock_service.get_wallet.side_effect = WalletNotFoundError("not found")

        resp = client.get(f"/agents/{AGENT_ID}/wallet")
        assert resp.status_code == 404


# ------------------------------------------------------------------
# PUT update wallet
# ------------------------------------------------------------------


class TestUpdateWallet:
    def test_update_200(self, client, mock_service):
        mock_service.update_wallet.return_value = _mock_wallet(service_budget_usd=10.0)

        resp = client.put(f"/agents/{AGENT_ID}/wallet", json={
            "service_budget_usd": 10.0,
        })

        assert resp.status_code == 200

    def test_update_404(self, client, mock_service):
        from agentarea_wallet.domain.exceptions import WalletNotFoundError
        mock_service.update_wallet.side_effect = WalletNotFoundError("not found")

        resp = client.put(f"/agents/{AGENT_ID}/wallet", json={
            "service_budget_usd": 10.0,
        })

        assert resp.status_code == 404


# ------------------------------------------------------------------
# DELETE wallet
# ------------------------------------------------------------------


class TestDeleteWallet:
    def test_delete_204(self, client, mock_service):
        mock_service.delete_wallet.return_value = None

        resp = client.delete(f"/agents/{AGENT_ID}/wallet")
        assert resp.status_code == 204

    def test_delete_404(self, client, mock_service):
        from agentarea_wallet.domain.exceptions import WalletNotFoundError
        mock_service.delete_wallet.side_effect = WalletNotFoundError("not found")

        resp = client.delete(f"/agents/{AGENT_ID}/wallet")
        assert resp.status_code == 404


# ------------------------------------------------------------------
# GET balance
# ------------------------------------------------------------------


class TestGetBalance:
    def test_balance_200(self, client, mock_service):
        mock_service.get_wallet.return_value = _mock_wallet(service_budget_usd=5.0)
        mock_service.get_total_spent_current_period.return_value = 2.0

        resp = client.get(f"/agents/{AGENT_ID}/wallet/balance")
        assert resp.status_code == 200
        data = resp.json()
        assert data["remaining"] == 3.0
        assert data["total_spent_current_period"] == 2.0

    def test_balance_404(self, client, mock_service):
        from agentarea_wallet.domain.exceptions import WalletNotFoundError
        mock_service.get_wallet.side_effect = WalletNotFoundError("not found")

        resp = client.get(f"/agents/{AGENT_ID}/wallet/balance")
        assert resp.status_code == 404


# ------------------------------------------------------------------
# GET payments
# ------------------------------------------------------------------


class TestGetPayments:
    def test_payments_200(self, client, mock_service):
        mock_service.get_payment_history.return_value = ([_mock_payment()], 1)

        resp = client.get(f"/agents/{AGENT_ID}/wallet/payments")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1
        assert data["page"] == 1

    def test_payments_200_with_filters(self, client, mock_service):
        mock_service.get_payment_history.return_value = ([], 0)

        resp = client.get(f"/agents/{AGENT_ID}/wallet/payments?protocol=x402&page=2&page_size=10")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0


# ------------------------------------------------------------------
# POST fund
# ------------------------------------------------------------------


class TestFundWallet:
    def test_fund_200(self, client, mock_service):
        mock_service.update_wallet.return_value = _mock_wallet(service_budget_usd=20.0)

        resp = client.post(f"/agents/{AGENT_ID}/wallet/fund", json={
            "service_budget_usd": 20.0,
        })

        assert resp.status_code == 200

    def test_fund_404(self, client, mock_service):
        from agentarea_wallet.domain.exceptions import WalletNotFoundError
        mock_service.update_wallet.side_effect = WalletNotFoundError("not found")

        resp = client.post(f"/agents/{AGENT_ID}/wallet/fund", json={
            "service_budget_usd": 20.0,
        })

        assert resp.status_code == 404
