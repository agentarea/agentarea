"""Unit/HTTP tests for the unified policy rule API and governance preview/snapshot."""

from datetime import UTC, datetime
from typing import ClassVar
from uuid import uuid4

import pytest
from agentarea_api.api.deps.services import get_temporal_workflow_service
from agentarea_api.api.v1 import governance, policies
from agentarea_api.api.v1.policies import (
    PolicyRuleCreateRequest,
    PolicyRuleUpdateRequest,
    create_policy_rule,
    delete_policy_rule,
    get_policy_rule,
    list_policy_rules,
    update_policy_rule,
)
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.dependencies import get_user_context
from agentarea_common.base.models import BaseModel
from agentarea_common.testing.flows import MainFlow
from agentarea_governance.domain.rules import PolicyEffect, PolicySubjectType
from agentarea_governance.infrastructure.orm import PolicyRuleORM
from agentarea_tasks.domain.models import Task
from agentarea_tasks.infrastructure.orm import TaskORM
from agentarea_tasks.infrastructure.repository import TaskRepository
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
                tables=[PolicyRuleORM.__table__, TaskORM.__table__],
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
    app.include_router(policies.router, prefix="/v1")
    app.include_router(governance.router, prefix="/v1")

    async def override_session():
        yield session

    async def override_user_context():
        return context

    app.dependency_overrides[policies.get_db_session] = override_session
    app.dependency_overrides[governance.get_db_session] = override_session
    app.dependency_overrides[get_user_context] = override_user_context
    return app


def _cap_request(amount: str = "25.00") -> PolicyRuleCreateRequest:
    return PolicyRuleCreateRequest(
        subject_type=PolicySubjectType.WORKSPACE,
        subject_id="workspace-a",
        target="spend",
        effect=PolicyEffect.CAP,
        params={"amount_usd": amount, "period": "month"},
    )


@pytest.mark.flow(MainFlow.GOVERNANCE_POLICIES)
def test_create_request_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        PolicyRuleCreateRequest.model_validate(
            {
                "subject_type": "workspace",
                "subject_id": "ws",
                "target": "spend",
                "effect": "cap",
                "bogus": True,
            }
        )


async def test_create_get_list_update_delete(session_factory):
    async with session_factory() as session:
        context = _context()

        created = await create_policy_rule(_cap_request("25.00"), context, session)
        assert created.effect == PolicyEffect.CAP
        assert created.params["amount_usd"] == "25.00"

        loaded = await get_policy_rule(created.id, context, session)
        assert loaded.id == created.id

        listed = await list_policy_rules(context, session)
        assert [r.id for r in listed] == [created.id]

        from agentarea_api.api.v1.policies import PolicyRuleUpdateRequest

        updated = await update_policy_rule(
            created.id,
            PolicyRuleUpdateRequest(enabled=False, priority=3),
            context,
            session,
        )
        assert updated.enabled is False
        assert updated.priority == 3

        resp = await delete_policy_rule(created.id, context, session)
        assert resp.status_code == 204

        with pytest.raises(HTTPException) as exc:
            await get_policy_rule(created.id, context, session)
        assert exc.value.status_code == 404


# ---- fail-closed write boundary: unenforceable rules must be rejected ----


async def test_create_rejects_group_subject(session_factory):
    async with session_factory() as session:
        context = _context()
        request = PolicyRuleCreateRequest(
            subject_type=PolicySubjectType.GROUP,
            subject_id="group:eng",
            target="tool:send_email",
            effect=PolicyEffect.DENY,
        )
        with pytest.raises(HTTPException) as exc:
            await create_policy_rule(request, context, session)
        assert exc.value.status_code == 422
        assert "group" in exc.value.detail.lower()


async def test_create_rejects_condition(session_factory):
    async with session_factory() as session:
        context = _context()
        request = PolicyRuleCreateRequest(
            subject_type=PolicySubjectType.WORKSPACE,
            subject_id="workspace-a",
            target="tool:send_email",
            effect=PolicyEffect.DENY,
            condition="resource.env == 'prod'",
        )
        with pytest.raises(HTTPException) as exc:
            await create_policy_rule(request, context, session)
        assert exc.value.status_code == 422
        assert "condition" in exc.value.detail.lower()


async def test_create_rejects_invalid_target(session_factory):
    async with session_factory() as session:
        context = _context()
        request = PolicyRuleCreateRequest(
            subject_type=PolicySubjectType.WORKSPACE,
            subject_id="workspace-a",
            target="tool_send_email",  # missing ':' -> unknown selector kind
            effect=PolicyEffect.DENY,
        )
        with pytest.raises(HTTPException) as exc:
            await create_policy_rule(request, context, session)
        assert exc.value.status_code == 422


async def test_create_rejects_cap_without_amount(session_factory):
    async with session_factory() as session:
        context = _context()
        request = PolicyRuleCreateRequest(
            subject_type=PolicySubjectType.WORKSPACE,
            subject_id="workspace-a",
            target="spend",
            effect=PolicyEffect.CAP,
            params={"period": "month"},  # no amount_usd -> silently dropped by compiler
        )
        with pytest.raises(HTTPException) as exc:
            await create_policy_rule(request, context, session)
        assert exc.value.status_code == 422
        assert "amount_usd" in exc.value.detail


async def test_update_rejects_condition(session_factory):
    async with session_factory() as session:
        context = _context()
        created = await create_policy_rule(_cap_request("25.00"), context, session)
        with pytest.raises(HTTPException) as exc:
            await update_policy_rule(
                created.id,
                PolicyRuleUpdateRequest(condition="x == 1"),
                context,
                session,
            )
        assert exc.value.status_code == 422


async def test_list_is_workspace_scoped(session_factory):
    async with session_factory() as session:
        context_a = _context("workspace-a")
        context_b = _context("workspace-b")
        await create_policy_rule(_cap_request(), context_a, session)

        assert await list_policy_rules(context_b, session) == []


async def test_http_crud_and_audit(session_factory, audit_capture):
    async with session_factory() as session:
        context = _context()
        app = _app_for(session, context)
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            created = await client.post(
                "/v1/policies",
                json={
                    "subject_type": "workspace",
                    "subject_id": context.workspace_id,
                    "target": "spend",
                    "effect": "cap",
                    "params": {"amount_usd": "25.00", "period": "month"},
                },
            )
            rule_id = created.json()["id"]
            listed = await client.get("/v1/policies")
            patched = await client.patch(
                f"/v1/policies/{rule_id}", json={"enabled": False}
            )
            deleted = await client.delete(f"/v1/policies/{rule_id}")

        assert created.status_code == 201
        body = created.json()
        assert body["effect"] == "cap"
        assert body["target"] == "spend"
        assert body["params"] == {"amount_usd": "25.00", "period": "month"}
        assert listed.status_code == 200
        assert listed.json()[0]["id"] == rule_id
        assert patched.json()["enabled"] is False
        assert deleted.status_code == 204

        actions = [c["action"] for c in audit_capture]
        assert "governance_policy.create" in actions
        assert "governance_policy.update" in actions
        assert "governance_policy.delete" in actions


async def test_http_filters_by_effect_and_subject(session_factory):
    async with session_factory() as session:
        context = _context()
        app = _app_for(session, context)
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post(
                "/v1/policies",
                json={
                    "subject_type": "workspace",
                    "subject_id": context.workspace_id,
                    "target": "tool:a",
                    "effect": "deny",
                },
            )
            await client.post(
                "/v1/policies",
                json={
                    "subject_type": "workspace",
                    "subject_id": context.workspace_id,
                    "target": "tool:b",
                    "effect": "allow",
                },
            )
            denied = await client.get("/v1/policies?effect=deny")

        assert denied.status_code == 200
        assert len(denied.json()) == 1
        assert denied.json()[0]["target"] == "tool:a"


async def test_get_missing_rule_returns_404(session_factory):
    async with session_factory() as session:
        context = _context()
        app = _app_for(session, context)
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            missing = await client.get(f"/v1/policies/{uuid4()}")

        assert missing.status_code == 404


# ---- governance preview + snapshot (resolved from rules) ----


async def test_preview_returns_workspace_cap_from_rules(session_factory):
    async with session_factory() as session:
        context = _context()
        app = _app_for(session, context)
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post(
                "/v1/policies",
                json={
                    "subject_type": "workspace",
                    "subject_id": context.workspace_id,
                    "target": "spend",
                    "effect": "cap",
                    "params": {"amount_usd": "50.00", "period": "month"},
                },
            )
            preview = await client.post("/v1/governance/effective-policy/preview", json={})

        assert preview.status_code == 200
        body = preview.json()["effective_policy"]
        assert body["budget"]["monthly_spend_cap_usd"] == "50.00"


async def test_preview_merges_workspace_and_agent_rules(session_factory):
    async with session_factory() as session:
        context = _context()
        agent_id = str(uuid4())
        app = _app_for(session, context)
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post(
                "/v1/policies",
                json={
                    "subject_type": "workspace",
                    "subject_id": context.workspace_id,
                    "target": "spend",
                    "effect": "cap",
                    "params": {"amount_usd": "100.00", "period": "month"},
                },
            )
            await client.post(
                "/v1/policies",
                json={
                    "subject_type": "agent",
                    "subject_id": agent_id,
                    "target": "spend",
                    "effect": "cap",
                    "params": {"amount_usd": "25.00", "period": "month"},
                },
            )
            preview = await client.post(
                "/v1/governance/effective-policy/preview",
                json={"agent_id": agent_id},
            )

        assert preview.status_code == 200
        assert preview.json()["effective_policy"]["budget"]["monthly_spend_cap_usd"] == "25.00"


async def test_preview_rejects_loosening_task_policy(session_factory):
    async with session_factory() as session:
        context = _context()
        app = _app_for(session, context)
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post(
                "/v1/policies",
                json={
                    "subject_type": "workspace",
                    "subject_id": context.workspace_id,
                    "target": "spend",
                    "effect": "cap",
                    "params": {"amount_usd": "10.00", "period": "month"},
                },
            )
            preview = await client.post(
                "/v1/governance/effective-policy/preview",
                json={"task_policy": {"budget": {"monthly_spend_cap_usd": "100.00"}}},
            )

        assert preview.status_code == 422
        assert "monthly_spend_cap_usd" in preview.json()["detail"]


async def test_reads_task_policy_from_workflow(session_factory):
    task_id = uuid4()
    execution_id = f"task-{task_id}"
    context = _context()

    class _FakeWorkflowService:
        async def get_effective_policy(self, exec_id: str):
            if exec_id == execution_id:
                return {"budget": {"run_budget_usd": "1.25"}}
            return None

    async with session_factory() as session:
        # Seed a task carrying an execution_id; the effective policy lives in the
        # workflow, served on demand by the (faked) workflow service.
        now = datetime.now(UTC)
        await TaskRepository(session, context).create_task(
            Task(
                id=task_id,
                agent_id=uuid4(),
                description="d",
                parameters={},
                status="submitted",
                created_at=now,
                updated_at=now,
                user_id=context.user_id,
                workspace_id=context.workspace_id,
                execution_id=execution_id,
            )
        )
        app = _app_for(session, context)
        app.dependency_overrides[get_temporal_workflow_service] = lambda: _FakeWorkflowService()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            found = await client.get(f"/v1/governance/task-policy-snapshots/{task_id}")
            missing = await client.get(f"/v1/governance/task-policy-snapshots/{uuid4()}")

        assert found.status_code == 200
        assert found.json()["effective_policy"]["budget"]["run_budget_usd"] == "1.25"
        assert missing.status_code == 404
