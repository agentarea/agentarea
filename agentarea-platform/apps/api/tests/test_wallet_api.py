"""API endpoint tests for wallet routes with mocked WalletService."""

from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from agentarea_api.api.deps.services import get_agent_service
from agentarea_api.api.v1.wallet import get_wallet_service, resolve_agent_id, router
from agentarea_common.auth.authorization import AuthorizationService
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.dependencies import get_user_context
from agentarea_common.auth.workspace_authorization import WorkspaceScopedAuthorizationService
from agentarea_common.di.container import register_singleton
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
    w.service_budget_usd = overrides.get("service_budget_usd", Decimal("5.000000"))
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
    p.amount_usd = overrides.get("amount_usd", Decimal("0.010000"))
    p.recipient = overrides.get("recipient", "0xabc")
    p.tx_hash = overrides.get("tx_hash", "0xdef")
    p.tool_name = overrides.get("tool_name", "weather")
    p.tool_call_id = overrides.get("tool_call_id", "tc_1")
    p.status = overrides.get("status", "completed")
    p.error_message = overrides.get("error_message", None)
    p.protocol_metadata = overrides.get("protocol_metadata", None)
    p.created_at = datetime.now()
    return p


class _DenyAuthorizationService(WorkspaceScopedAuthorizationService):
    """A workspace member who does not own it: may write entities, may not administer."""

    async def can_administer_workspace(self, user_context, workspace_id) -> bool:
        return False


@pytest.fixture(autouse=True)
def _register_authz():
    # Default: admin, matching the OSS one-owner-per-workspace model. Tests that
    # exercise the non-admin path register _DenyAuthorizationService instead.
    register_singleton(AuthorizationService, WorkspaceScopedAuthorizationService())


@pytest.fixture
def mock_service():
    return AsyncMock()


@pytest.fixture
def client(mock_service):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_wallet_service] = lambda: mock_service
    app.dependency_overrides[resolve_agent_id] = lambda: UUID(AGENT_ID)
    # Wallet credentials and budgets are admin-gated; act as the workspace owner.
    app.dependency_overrides[get_user_context] = lambda: UserContext(
        user_id="user-1", workspace_id="ws-1", admin_workspaces=["ws-1"]
    )
    return TestClient(app)


AGENT_ID = str(uuid4())


# ------------------------------------------------------------------
# POST create wallet
# ------------------------------------------------------------------


@pytest.mark.flow(MainFlow.WALLET_PAYMENTS)
class TestCreateWallet:
    def test_create_201(self, client, mock_service):
        mock_service.create_wallet.return_value = _mock_wallet()

        resp = client.post(
            f"/agents/{AGENT_ID}/wallet",
            json={
                "wallet_type": "x402",
                "x402_config": {"network": "eip155:8453"},
                "service_budget_usd": 5.0,
                "service_budget_period": "execution",
            },
        )

        assert resp.status_code == 201
        data = resp.json()
        assert data["wallet_type"] == "dual"
        assert data["has_credentials"] is True

    def test_create_mpp_wallet_without_a_session_budget_is_rejected(self, client, mock_service):
        resp = client.post(
            f"/agents/{AGENT_ID}/wallet",
            json={
                "wallet_type": "mpp",
                "mpp_config": {"payment_method_types": ["charge"]},
                "service_budget_usd": "5",
            },
        )

        assert resp.status_code == 422
        assert "session_budget_usd" in resp.text
        mock_service.create_wallet.assert_not_called()

    def test_create_passes_budgets_as_decimal(self, client, mock_service):
        mock_service.create_wallet.return_value = _mock_wallet()

        resp = client.post(
            f"/agents/{AGENT_ID}/wallet",
            json={
                "wallet_type": "mpp",
                "mpp_config": {"session_budget_usd": 0.1},
                "service_budget_usd": 0.3,
            },
        )

        assert resp.status_code == 201
        kwargs = mock_service.create_wallet.call_args.kwargs
        assert kwargs["service_budget_usd"] == Decimal("0.3")
        assert kwargs["mpp_config"]["session_budget_usd"] == "0.1"
        assert resp.json()["service_budget_usd"] == "5.000000"

    def test_create_409_duplicate(self, client, mock_service):
        from agentarea_wallet.domain.exceptions import WalletAlreadyExistsError

        mock_service.create_wallet.side_effect = WalletAlreadyExistsError("exists")

        resp = client.post(
            f"/agents/{AGENT_ID}/wallet",
            json={
                "wallet_type": "x402",
                "x402_config": {"network": "eip155:8453"},
            },
        )

        assert resp.status_code == 409

    def test_create_400_validation(self, client, mock_service):
        mock_service.create_wallet.side_effect = ValueError("x402_config required")

        resp = client.post(
            f"/agents/{AGENT_ID}/wallet",
            json={
                "wallet_type": "x402",
            },
        )

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

        resp = client.put(
            f"/agents/{AGENT_ID}/wallet",
            json={
                "service_budget_usd": 10.0,
            },
        )

        assert resp.status_code == 200

    def test_update_404(self, client, mock_service):
        from agentarea_wallet.domain.exceptions import WalletNotFoundError

        mock_service.update_wallet.side_effect = WalletNotFoundError("not found")

        resp = client.put(
            f"/agents/{AGENT_ID}/wallet",
            json={
                "service_budget_usd": 10.0,
            },
        )

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
        mock_service.get_wallet.return_value = _mock_wallet(service_budget_usd=Decimal("0.3"))
        mock_service.get_total_spent_current_period.return_value = Decimal("0.1") + Decimal("0.1")

        resp = client.get(f"/agents/{AGENT_ID}/wallet/balance")
        assert resp.status_code == 200
        data = resp.json()
        assert data["service_budget_usd"] == "0.3"
        assert data["remaining"] == "0.1"
        assert data["total_spent_current_period"] == "0.2"

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
        assert data["items"][0]["amount_usd"] == "0.010000"
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

        resp = client.post(
            f"/agents/{AGENT_ID}/wallet/fund",
            json={
                "service_budget_usd": 20.0,
            },
        )

        assert resp.status_code == 200

    def test_fund_404(self, client, mock_service):
        from agentarea_wallet.domain.exceptions import WalletNotFoundError

        mock_service.update_wallet.side_effect = WalletNotFoundError("not found")

        resp = client.post(
            f"/agents/{AGENT_ID}/wallet/fund",
            json={
                "service_budget_usd": 20.0,
            },
        )

        assert resp.status_code == 404


# ------------------------------------------------------------------
# Mutations require workspace admin, not just membership
# ------------------------------------------------------------------


class TestWalletMutationsRequireAdmin:
    def test_fund_403_for_non_admin(self, client, mock_service):
        register_singleton(AuthorizationService, _DenyAuthorizationService())

        resp = client.post(
            f"/agents/{AGENT_ID}/wallet/fund",
            json={
                "service_budget_usd": 20.0,
            },
        )

        assert resp.status_code == 403
        mock_service.update_wallet.assert_not_called()

    def test_delete_403_for_non_admin(self, client, mock_service):
        register_singleton(AuthorizationService, _DenyAuthorizationService())

        resp = client.delete(f"/agents/{AGENT_ID}/wallet")

        assert resp.status_code == 403
        mock_service.delete_wallet.assert_not_called()


# ------------------------------------------------------------------
# The path names the agent by UUID or by slug, as the webapp URLs do
# ------------------------------------------------------------------


class _FakeAgentService:
    def __init__(self, agent_id, slug):
        self._agent = MagicMock(id=agent_id, slug=slug)

    async def get(self, agent_id):
        return self._agent if agent_id == self._agent.id else None

    async def get_by_slug(self, slug):
        return self._agent if slug == self._agent.slug else None


@pytest.fixture
def agent_client(mock_service):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_wallet_service] = lambda: mock_service
    app.dependency_overrides[get_agent_service] = lambda: _FakeAgentService(
        AGENT_UUID, "seo-machine-metrica"
    )
    app.dependency_overrides[get_user_context] = lambda: UserContext(
        user_id="user-1", workspace_id="ws-1", admin_workspaces=["ws-1"]
    )
    return TestClient(app)


AGENT_UUID = uuid4()


class TestAgentReference:
    def test_payments_by_slug_query_the_agent_uuid(self, agent_client, mock_service):
        mock_service.get_payment_history.return_value = ([], 0)

        resp = agent_client.get("/agents/seo-machine-metrica/wallet/payments")

        assert resp.status_code == 200
        assert mock_service.get_payment_history.call_args.kwargs["agent_id"] == str(AGENT_UUID)

    def test_wallet_by_slug_reads_the_agent_uuid(self, agent_client, mock_service):
        mock_service.get_wallet.return_value = _mock_wallet(agent_id=AGENT_UUID)

        resp = agent_client.get("/agents/seo-machine-metrica/wallet")

        assert resp.status_code == 200
        mock_service.get_wallet.assert_called_once_with(str(AGENT_UUID))

    def test_payments_by_uuid(self, agent_client, mock_service):
        mock_service.get_payment_history.return_value = ([], 0)

        resp = agent_client.get(f"/agents/{AGENT_UUID}/wallet/payments")

        assert resp.status_code == 200
        assert mock_service.get_payment_history.call_args.kwargs["agent_id"] == str(AGENT_UUID)

    def test_unknown_slug_is_404(self, agent_client, mock_service):
        resp = agent_client.get("/agents/no-such-agent/wallet/payments")

        assert resp.status_code == 404
        mock_service.get_payment_history.assert_not_called()

    def test_unknown_uuid_is_404(self, agent_client, mock_service):
        resp = agent_client.get(f"/agents/{uuid4()}/wallet/payments")

        assert resp.status_code == 404
        mock_service.get_payment_history.assert_not_called()
