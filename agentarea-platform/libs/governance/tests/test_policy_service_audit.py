"""Creating a governance rule audits the rule, not the subject it applies to.

``governance_policy.create`` used to take its resource id from ``subject_id``, so
the audit log named the agent or workspace the rule covered as if it were the
policy, and the audit page linked to a policy that does not exist.
"""

import pytest
from agentarea_common.audit.models import AuditEventORM
from agentarea_common.auth.authorization import AuthorizationService
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.workspace_authorization import WorkspaceScopedAuthorizationService
from agentarea_common.base.models import BaseModel
from agentarea_common.base.repository_factory import RepositoryFactory
from agentarea_common.di.container import get_container
from agentarea_governance.application.service import GovernancePolicyService
from agentarea_governance.domain.rules import PolicyEffect, PolicyRule, PolicySubjectType
from agentarea_governance.infrastructure.orm import PolicyRuleORM
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

WORKSPACE = "ws-acme"
AGENT_ID = "agent-covered-by-the-rule"


@pytest.fixture(autouse=True)
def _authorization():
    container = get_container()
    saved = dict(container._singletons)
    container.register_singleton(AuthorizationService, WorkspaceScopedAuthorizationService())
    yield
    container._singletons.clear()
    container._singletons.update(saved)


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: BaseModel.metadata.create_all(
                sync_conn, tables=[PolicyRuleORM.__table__, AuditEventORM.__table__]
            )
        )
    try:
        async with async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)() as s:
            yield s
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_create_audits_the_created_rule(session) -> None:
    admin = UserContext(user_id="user-owner", workspace_id=WORKSPACE, admin_workspaces=[WORKSPACE])
    service = GovernancePolicyService(RepositoryFactory(session, admin))

    created = await service.create_rule(
        rule=PolicyRule(
            subject_type=PolicySubjectType.AGENT,
            subject_id=AGENT_ID,
            target="tool:shell",
            effect=PolicyEffect.DENY,
        )
    )

    events = (
        await session.scalars(
            select(AuditEventORM).where(AuditEventORM.action == "governance_policy.create")
        )
    ).all()
    assert [event.resource_id for event in events] == [str(created.id)]
