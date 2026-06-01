"""Unit tests for governance policy API functions."""

from typing import ClassVar
from uuid import uuid4

import pytest
from agentarea_api.api.v1 import governance
from agentarea_api.api.v1.governance import (
    PolicyUpsertRequest,
    get_policy,
    get_task_policy_snapshot,
    list_policies,
    upsert_policy,
)
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.dependencies import get_user_context
from agentarea_common.base.models import BaseModel
from agentarea_governance.domain.policies import (
    BudgetPolicy,
    EffectivePolicy,
    PolicyDocument,
)
from agentarea_governance.infrastructure.orm import (
    GovernancePolicyORM,
    TaskPolicySnapshotORM,
)
from agentarea_governance.infrastructure.repository import TaskPolicySnapshotRepository
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


class _FakeAuditService:
    calls: ClassVar[list[dict]] = []

    def __init__(self, session, user_context):
        self.session = session
        self.user_context = user_context

    async def record(self, **kwargs):
        self.calls.append(kwargs)


@pytest.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: BaseModel.metadata.create_all(
                sync_conn,
                tables=[GovernancePolicyORM.__table__, TaskPolicySnapshotORM.__table__],
            )
        )
    try:
        yield async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    finally:
        await engine.dispose()


@pytest.fixture(autouse=True)
def audit_capture(monkeypatch):
    _FakeAuditService.calls = []
    monkeypatch.setattr("agentarea_common.audit.decorator.AuditService", _FakeAuditService)
    return _FakeAuditService.calls


def _context(workspace_id: str = "workspace-a") -> UserContext:
    return UserContext(user_id=f"user-{workspace_id}", workspace_id=workspace_id)


def _app_for(session: AsyncSession, context: UserContext) -> FastAPI:
    app = FastAPI()
    app.include_router(governance.router, prefix="/v1")

    async def override_session():
        yield session

    async def override_user_context():
        return context

    app.dependency_overrides[governance.get_db_session] = override_session
    app.dependency_overrides[get_user_context] = override_user_context
    return app


def test_policy_upsert_request_rejects_unknown_policy_fields():
    with pytest.raises(ValidationError):
        PolicyUpsertRequest.model_validate({"document": {"unknown": {"enabled": True}}})


async def test_policy_api_upserts_gets_and_lists_workspace_policy(session_factory):
    async with session_factory() as session:
        context = _context()
        payload = PolicyUpsertRequest(
            document=PolicyDocument(budget=BudgetPolicy(monthly_spend_cap_usd="25.00"))
        )

        saved = await upsert_policy("workspace", context.workspace_id, payload, context, session)
        loaded = await get_policy("workspace", context.workspace_id, context, session)
        listed = await list_policies(context, session)

        assert saved.id == loaded.id
        assert str(loaded.document.budget.monthly_spend_cap_usd) == "25.00"
        assert [record.id for record in listed] == [saved.id]


async def test_policy_api_list_is_workspace_scoped(session_factory):
    async with session_factory() as session:
        context_a = _context("workspace-a")
        context_b = _context("workspace-b")

        await upsert_policy(
            "workspace",
            context_a.workspace_id,
            PolicyUpsertRequest(document=PolicyDocument()),
            context_a,
            session,
        )

        assert await list_policies(context_b, session) == []


async def test_policy_api_rejects_agent_policy_that_loosens_workspace_policy(
    session_factory,
):
    async with session_factory() as session:
        context = _context()
        await upsert_policy(
            "workspace",
            context.workspace_id,
            PolicyUpsertRequest(
                document=PolicyDocument(budget=BudgetPolicy(monthly_spend_cap_usd="100.00"))
            ),
            context,
            session,
        )

        with pytest.raises(HTTPException) as exc_info:
            await upsert_policy(
                "agent",
                str(uuid4()),
                PolicyUpsertRequest(
                    document=PolicyDocument(
                        budget=BudgetPolicy(monthly_spend_cap_usd="200.00")
                    )
                ),
                context,
                session,
            )

        assert exc_info.value.status_code == 422
        assert "monthly_spend_cap_usd" in exc_info.value.detail


async def test_policy_api_reads_task_policy_snapshot(session_factory):
    task_id = uuid4()
    context = _context()
    effective = EffectivePolicy(budget=BudgetPolicy(run_budget_usd="1.25"))

    async with session_factory() as session:
        await TaskPolicySnapshotRepository(session, context).create_snapshot(
            task_id=task_id,
            effective_policy=effective,
        )

        response = await get_task_policy_snapshot(task_id, context, session)

        assert str(response.effective_policy.budget.run_budget_usd) == "1.25"


async def test_policy_http_upserts_gets_lists_and_audits_workspace_policy(
    session_factory, audit_capture
):
    async with session_factory() as session:
        context = _context()
        app = _app_for(session, context)
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            saved = await client.put(
                f"/v1/governance/policies/workspace/{context.workspace_id}",
                json={"document": {"budget": {"monthly_spend_cap_usd": "25.00"}}},
            )
            loaded = await client.get(
                f"/v1/governance/policies/workspace/{context.workspace_id}"
            )
            listed = await client.get("/v1/governance/policies")

        assert saved.status_code == 200
        assert loaded.status_code == 200
        assert listed.status_code == 200
        assert loaded.json()["id"] == saved.json()["id"]
        assert listed.json()[0]["id"] == saved.json()["id"]
        assert loaded.json()["document"]["budget"]["monthly_spend_cap_usd"] == "25.00"
        assert audit_capture == [
            {
                "action": "governance_policy.upsert",
                "resource_type": "governance_policy",
                "resource_id": context.workspace_id,
                "changes": None,
            }
        ]


async def test_policy_http_rejects_unknown_fields_and_lower_scope_loosening(session_factory):
    async with session_factory() as session:
        context = _context()
        app = _app_for(session, context)
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            unknown = await client.put(
                f"/v1/governance/policies/workspace/{context.workspace_id}",
                json={"document": {"unknown": {"enabled": True}}},
            )
            await client.put(
                f"/v1/governance/policies/workspace/{context.workspace_id}",
                json={"document": {"budget": {"monthly_spend_cap_usd": "100.00"}}},
            )
            loosened = await client.put(
                f"/v1/governance/policies/agent/{uuid4()}",
                json={"document": {"budget": {"monthly_spend_cap_usd": "200.00"}}},
            )

        assert unknown.status_code == 422
        assert loosened.status_code == 422
        assert "monthly_spend_cap_usd" in loosened.json()["detail"]


async def test_policy_http_reads_task_policy_snapshot_and_returns_404_for_missing(
    session_factory,
):
    task_id = uuid4()
    context = _context()
    effective = EffectivePolicy(budget=BudgetPolicy(run_budget_usd="1.25"))

    async with session_factory() as session:
        await TaskPolicySnapshotRepository(session, context).create_snapshot(
            task_id=task_id,
            effective_policy=effective,
        )
        app = _app_for(session, context)
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            found = await client.get(f"/v1/governance/task-policy-snapshots/{task_id}")
            missing = await client.get(f"/v1/governance/task-policy-snapshots/{uuid4()}")

        assert found.status_code == 200
        assert found.json()["effective_policy"]["budget"]["run_budget_usd"] == "1.25"
        assert missing.status_code == 404


async def test_preview_returns_workspace_policy_when_only_workspace_defined(session_factory):
    async with session_factory() as session:
        context = _context()
        app = _app_for(session, context)
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.put(
                f"/v1/governance/policies/workspace/{context.workspace_id}",
                json={"document": {"budget": {"monthly_spend_cap_usd": "50.00"}}},
            )

            preview = await client.post(
                "/v1/governance/effective-policy/preview",
                json={},
            )

        assert preview.status_code == 200
        body = preview.json()["effective_policy"]
        assert body["budget"]["monthly_spend_cap_usd"] == "50.00"


async def test_preview_merges_workspace_and_agent_policies(session_factory):
    async with session_factory() as session:
        context = _context()
        agent_id = str(uuid4())
        app = _app_for(session, context)
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.put(
                f"/v1/governance/policies/workspace/{context.workspace_id}",
                json={"document": {"budget": {"monthly_spend_cap_usd": "100.00"}}},
            )
            await client.put(
                f"/v1/governance/policies/agent/{agent_id}",
                json={"document": {"budget": {"monthly_spend_cap_usd": "25.00"}}},
            )

            preview = await client.post(
                "/v1/governance/effective-policy/preview",
                json={"agent_id": agent_id},
            )

        assert preview.status_code == 200
        body = preview.json()["effective_policy"]
        # Tighter agent cap wins
        assert body["budget"]["monthly_spend_cap_usd"] == "25.00"


async def test_preview_accepts_tightening_task_policy(session_factory):
    async with session_factory() as session:
        context = _context()
        app = _app_for(session, context)
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.put(
                f"/v1/governance/policies/workspace/{context.workspace_id}",
                json={"document": {"budget": {"monthly_spend_cap_usd": "100.00"}}},
            )

            preview = await client.post(
                "/v1/governance/effective-policy/preview",
                json={
                    "task_policy": {"budget": {"monthly_spend_cap_usd": "10.00"}}
                },
            )

        assert preview.status_code == 200
        body = preview.json()["effective_policy"]
        assert body["budget"]["monthly_spend_cap_usd"] == "10.00"


async def test_preview_rejects_loosening_task_policy(session_factory):
    async with session_factory() as session:
        context = _context()
        app = _app_for(session, context)
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.put(
                f"/v1/governance/policies/workspace/{context.workspace_id}",
                json={"document": {"budget": {"monthly_spend_cap_usd": "10.00"}}},
            )

            preview = await client.post(
                "/v1/governance/effective-policy/preview",
                json={
                    "task_policy": {"budget": {"monthly_spend_cap_usd": "100.00"}}
                },
            )

        assert preview.status_code == 422
        assert "monthly_spend_cap_usd" in preview.json()["detail"]
